from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillCandidate,
    AuthoringPrefillCompositeAdoptReceipt,
    AuthoringPrefillCompositeAdoptResult,
    AuthoringPrefillCompositeAdoptRequest,
    AuthoringPrefillCompositeSkippedPath,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingAuthoringStageDraft,
    MedicalWritingDocumentCreationReservation,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingCompetitorSearchPlan,
    medical_writing_competitor_search_contract,
    MedicalWritingCorpusGate,
    MedicalWritingCorpusGateOverride,
    MedicalWritingCorpusGateOverrideRequest,
    MedicalWritingCorpusRequirementStatus,
    MedicalWritingCorpusTriage,
    MedicalWritingCorpusTriageFinalizeRequest,
    DiscoveryBasketProjection,
    MedicalWritingJourneyImpactPreview,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingMinimumProductFactPacket,
    MedicalWritingPicosCorpusAlignment,
    MedicalWritingPicosCorpusAlignmentRequest,
    MedicalWritingProductEvidenceFact,
    MedicalWritingSynopsisImport,
    MedicalWritingSynopsisImportConfirmRequest,
    MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFactEvidence,
    MedicalWritingStudyFactState,
    MedicalWritingStudySchemaCommitRequest,
    MedicalWritingStudySchemaDefinition,
    MedicalWritingStudySchemaEdge,
    MedicalWritingStudySchemaImpactPreview,
    MedicalWritingStudySchemaImpactPreviewRequest,
    MedicalWritingStudySchemaLayoutUpdateRequest,
    MedicalWritingStudySchemaNode,
    MedicalWritingStudySchemaPart,
    MedicalWritingStudySchemaPresentation,
    MedicalWritingStudySchemaSnapshot,
    MedicalWritingStudySchemaSourceBinding,
    WritingReferenceSearchCreateRequest,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
)

from .medical_writing_authoring_prefill import (
    EvidencePathVerifier,
    PrefillRankingAdapter,
    SUPPORTED_ADOPT_PATHS,
    effective_authoring_values,
    generate_prefill_package,
    journey_input_fingerprint,
    lock_confirmed_synopsis_values,
    map_design_adoption_to_study_updates,
    package_is_stale,
    plan_composite_adoption,
    preserve_current_user_confirmations,
    search_fingerprint,
    values_materially_distinct,
)

from .medical_writing_study_schema import (
    StudySchemaPlanConflictError,
    canonical_payload_sha256,
    formal_render_allowed,
    render_study_schema_svg,
    require_plan_for_study_schema,
    study_schema_state_sha256,
    validate_study_schema,
    validate_study_schema_against_plan,
)
from .medical_writing_design_projection import normalize_study_design



SCHEMA_VERSION = 2

# Durable in-flight generation reservation (worker_02 corrective round):
# keyed by (project_id, expected_revision, operation) in the journey store
# so a second logical call from a duplicate key or a restarted worker can
# never dispatch another enrichment while the first call is in flight.
_GENERATION_RESERVATION_OPERATION = "prefill_generate"

# Note written when a waiter's deadline flips an observed in-flight call to
# unknown_outcome.  When the owner later completes the same logical call,
# this note is cleared (the owner was not interrupted after all); supersede
# notes ("supersedes … call") are preserved on the completed row as lineage.
_WAITER_DEADLINE_FLIP_NOTE = (
    "in-flight reservation observed beyond the wait "
    "bound; owner presumed interrupted/restarted"
)


@dataclass(frozen=True)
class _GenerationReservationAcquisition:
    """Outcome of attempting to acquire a durable generation reservation.

    Exactly one of ``logical_call_id`` (this caller owns a fresh
    reservation) or ``replay`` (the generation for this key already
    completed; the caller returns the winner's outcome) is set.

    Replay contract (worker_03 corrective round): ``replay`` is the
    CURRENT journey state, which may be a later revision than the key's
    ``expected_revision`` when a subsequent force regeneration superseded
    the completed outcome.  ``replay_event_id`` / ``replay_event_revision``
    carry the completion event metadata (verified against the key) so a
    caller can explain a refresh: the generation that completed this key
    produced journey revision ``expected_revision + 1`` (or later).
    """

    logical_call_id: str | None = None
    replay: "MedicalWritingAuthoringJourney | None" = None
    replay_event_id: str | None = None
    replay_event_revision: int | None = None


LEGACY_BOOTSTRAP_CONFIRMED_PATHS = frozenset(
    {
        "framing.protocol_id",
        "framing.version",
        "framing.document_title",
        "framing.indication",
        "framing.study_phase",
        "framing.investigational_product",
        "framing.target_mechanism",
        "framing.design_pattern",
        "framing.population_intent",
        "picos.population_summary",
        "picos.intervention_summary",
        "picos.comparator_summary",
        "picos.primary_endpoint",
    }
)


class MedicalWritingAuthoringJourneyConflictError(ValueError):
    """Raised for duplicate, stale, or unconfirmed authoring-journey writes."""


def _load_authoring_journey_payload(
    payload_json: str,
) -> MedicalWritingAuthoringJourney:
    """Project historical journey payloads onto the current Protocol-only contract.

    Early journey records allowed ``search_plan.document_roles`` to include
    ``sap``. SAP is no longer part of protocol-corpus discovery, but the stored
    JSON remains immutable audit evidence. Normalize only the in-memory
    consumer projection so historical projects remain readable.
    """

    payload = json.loads(payload_json)
    search_plan = payload.get("search_plan")
    if isinstance(search_plan, dict):
        search_plan["document_roles"] = ["protocol"]
    return MedicalWritingAuthoringJourney.model_validate(payload)


class MedicalWritingAuthoringJourneyService:
    _CORPUS_REQUIREMENTS = [
        "竞品候选研究已完成人工相关性分诊",
        "至少一份相关Protocol已完成内容校验与结构化解析",
        "英文竞品方案关键章节已形成监管中文参考译文",
        "项目适用中文语料已完成医学准入",
        "PICOS关键设计事实与语料冲突已处置",
    ]

    _PRODUCT_DECISIONS = {
        "terminology": "cde_participant",
        "guide": "guided_groups",
        "corpus_gate": "blocking_override",
        "competitor": "broad_then_triage",
        "ai_candidates": "adaptive",
        "schema_editor": "semantic_limited_drag",
        "scales": "draft_translation",
        "second_port": "monitoring",
    }

    _IMPACT_MAP = {
        "framing.protocol_id": ["front_matter", "document_identity"],
        "framing.version": ["front_matter", "document_identity"],
        "framing.document_title": ["front_matter", "protocol_synopsis"],
        "framing.indication": [
            "competitor_search_plan",
            "corpus_coverage",
            "picos_recommendations",
            "m11_section_applicability",
        ],
        "framing.clinicaltrials_condition_term": [
            "competitor_search_plan",
            "corpus_coverage",
        ],
        "framing.study_phase": [
            "competitor_search_plan",
            "corpus_coverage",
            "m11_section_applicability",
            "statistical_design",
        ],
        "framing.intrinsic_objectives": [
            "competitor_search_plan",
            "objectives_endpoints",
            "protocol_synopsis",
        ],
        "framing.investigational_product": ["front_matter", "intervention_sections"],
        "framing.product_profile.technology_type": [
            "competitor_search_plan",
            "corpus_coverage",
            "phase1_design",
            "safety_assessments",
            "pk_pd_strategy",
        ],
        "framing.product_profile.administration_routes": [
            "competitor_search_plan",
            "corpus_coverage",
            "intervention_sections",
            "schedule_of_activities",
            "safety_assessments",
            "pk_pd_strategy",
        ],
        "framing.product_profile.dosage_forms": [
            "competitor_search_plan",
            "intervention_sections",
            "pharmacy_handling",
        ],
        "framing.product_profile.exposure_scope": [
            "competitor_search_plan",
            "safety_assessments",
            "pk_pd_strategy",
        ],
        "framing.product_profile.device_dependency": [
            "intervention_sections",
            "device_handling",
            "safety_assessments",
        ],
        "framing.product_profile.immunogenicity_relevance": [
            "safety_assessments",
            "immunogenicity_strategy",
            "schedule_of_activities",
        ],
        "framing.product_profile.safety_considerations": [
            "safety_assessments",
            "eligibility_sections",
            "dose_modification_rules",
        ],
        "framing.product_profile.pk_pd_considerations": [
            "pk_pd_strategy",
            "schedule_of_activities",
            "objectives_endpoints",
        ],
        "framing.minimum_product_fact_packet": [
            "corpus_coverage",
            "trial_rationale",
            "safety_assessments",
            "intervention_sections",
        ],
        "framing.target_mechanism": [
            "competitor_search_plan",
            "corpus_coverage",
            "trial_rationale",
        ],
        "framing.competitor_target_scope": ["competitor_search_plan", "corpus_coverage"],
        "framing.design_pattern": [
            "picos_recommendations",
            "protocol_synopsis",
            "study_schema",
            "schedule_of_activities",
        ],
        "framing.structured_design": [
            "picos_recommendations",
            "protocol_synopsis",
            "m11_section_applicability",
            "study_schema",
            "schedule_of_activities",
            "statistical_design",
        ],
        "framing.population_intent": [
            "eligibility_sections",
            "picos_recommendations",
            "protocol_synopsis",
        ],
        "framing.development_regions": ["corpus_coverage", "regional_requirements"],
        "picos.population_summary": [
            "eligibility_sections",
            "protocol_synopsis",
            "estimands",
            "schedule_of_activities",
        ],
        "picos.inclusion_modules": ["eligibility_sections", "screening_activities"],
        "picos.exclusion_modules": ["eligibility_sections", "screening_activities"],
        "picos.washout_rules": ["eligibility_sections", "schedule_of_activities"],
        "picos.intervention_summary": [
            "intervention_sections",
            "protocol_synopsis",
            "study_schema",
        ],
        "picos.intervention_dose_regimen": [
            "intervention_sections",
            "dose_modification_rules",
            "schedule_of_activities",
        ],
        "picos.allowed_concomitant_rules": ["concomitant_therapy_rules"],
        "picos.required_background_rules": ["non_investigational_interventions"],
        "picos.prohibited_concomitant_rules": ["concomitant_therapy_rules"],
        "picos.assessment_timing_restrictions": ["schedule_of_activities"],
        "picos.intervention_rules": [
            "intervention_sections",
            "protocol_synopsis",
            "study_schema",
            "dose_modification_rules",
            "non_investigational_interventions",
            "concomitant_therapy_rules",
            "schedule_of_activities",
        ],
        "picos.comparator_summary": ["protocol_synopsis", "study_schema"],
        "picos.primary_endpoint": [
            "objectives_endpoints",
            "estimands",
            "sample_size",
            "schedule_of_activities",
        ],
        "picos.key_secondary_endpoints": ["objectives_endpoints", "multiplicity", "schedule_of_activities"],
        "picos.other_secondary_endpoints": ["objectives_endpoints", "schedule_of_activities"],
        "picos.exploratory_endpoints": ["objectives_endpoints", "schedule_of_activities"],
        "picos.safety_endpoints": ["safety_assessments", "schedule_of_activities"],
        "picos.aesi_definitions": ["safety_reporting", "safety_assessments"],
        "picos.assessment_instruments": [
            "objectives_endpoints",
            "eligibility_sections",
            "schedule_of_activities",
            "instrument_appendices",
        ],
        "picos.study_epochs": ["study_schema", "schedule_of_activities", "protocol_synopsis"],
        "picos.visit_strategy": ["schedule_of_activities", "study_schema"],
        "picos.estimand_strategy": ["estimands", "statistical_analysis"],
        "picos.sample_size_strategy": ["sample_size", "statistical_analysis"],
        "picos.statistical_strategy": ["statistical_analysis", "protocol_synopsis"],
    }

    def __init__(
        self,
        db_path: Path,
        plan_consumption_helper: Any = None,
        generation_reservation_wait_seconds: float | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._plan_helper = plan_consumption_helper
        # Bounded wait for a competing in-flight generation reservation; a
        # test hook that keeps duplicate-worker tests deterministic.  When
        # None the wait covers the enrichment timeout plus margin.
        self._generation_reservation_wait_seconds = generation_reservation_wait_seconds
        self._initialize()

    def bind_plan_consumption_helper(self, plan_consumption_helper: Any) -> None:
        """Inject the plan helper after construction (serial DI in main)."""
        self._plan_helper = plan_consumption_helper

    def _require_study_schema_plan(self, project_id: str) -> Any:
        """Consume confirmed study_schema_flowchart projection or fail closed.

        Production always binds the helper via main.py. When unbound (unit tests
        that do not exercise plan paths), returns None for backward compatibility.
        """
        if self._plan_helper is None:
            return None
        return require_plan_for_study_schema(project_id, self._plan_helper)

    def _require_study_schema_design_projection(
        self,
        definition: MedicalWritingStudyDefinition,
    ) -> tuple[Any, Any]:
        if self._plan_helper is None:
            return None, normalize_study_design(
                definition, include_sources=True
            )
        state, current_definition, projection = (
            self._plan_helper.require_confirmed_design_projection(
                project_id=definition.project_id,
                projection_kind="study_schema_flowchart",
            )
        )
        if (
            current_definition.definition_id,
            current_definition.revision,
            current_definition.state_sha256,
        ) != (
            definition.definition_id,
            definition.revision,
            definition.state_sha256,
        ):
            raise StudySchemaPlanConflictError(
                "study schema input does not match the confirmed plan source"
            )
        return state, projection

    def _align_schema_with_plan(
        self,
        project_id: str,
        schema: MedicalWritingStudySchemaDefinition,
    ) -> Any:
        plan_state = self._require_study_schema_plan(project_id)
        if plan_state is None:
            return None
        plan_issues = validate_study_schema_against_plan(schema, plan_state)
        blockers = [item for item in plan_issues if item.severity == "blocker"]
        if blockers:
            raise StudySchemaPlanConflictError(
                "study schema conflicts with confirmed ProtocolAssemblyPlan: "
                + "；".join(item.message for item in blockers)
            )
        return plan_state

    def product_configuration(self) -> dict[str, Any]:
        return {
            "configuration_version": "medical_writing_gap_decisions_2026-07-14.v1",
            "decisions": dict(self._PRODUCT_DECISIONS),
            "participant_terminology_default": "试验参与者",
            "participant_terminology_project_override_allowed": True,
        }

    def has_project(self, project_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM medical_writing_authoring_journeys WHERE project_id = ?",
                (project_id,),
            ).fetchone() is not None

    def create(
        self,
        project_id: str,
        request: MedicalWritingAuthoringJourneyCreateRequest,
    ) -> MedicalWritingAuthoringJourney:
        project_id = _required_text(project_id, "project_id")
        request_payload = request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        request_sha256 = _payload_sha256(request_payload)
        now = datetime.now(timezone.utc)
        journey_id = "mwjourney_" + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20]
        framing = self._bootstrap_minimum_product_fact_packet(request.framing, now)
        framing_complete = not framing.missing_required_fields()
        search_ready = framing.creation_minimum_complete()
        study_definition = _build_study_definition(
            project_id=project_id,
            revision=1,
            origin=request.entry_mode,
            framing=framing,
            picos=None,
            synopsis_import=None,
            confirmed_stages={"framing"} if framing_complete else set(),
            actor=request.actor,
            now=now,
            confirmed_paths={
                "framing.investigational_product",
                "framing.indication",
                "framing.study_phase",
            },
        )
        state = MedicalWritingAuthoringJourney(
            journey_id=journey_id,
            project_id=project_id,
            revision=1,
            entry_mode=request.entry_mode,
            study_definition=study_definition,
            status="stage1_complete" if framing_complete else "stage1_in_progress",
            current_stage="picos" if framing_complete else "framing",
            framing=framing,
            framing_complete=framing_complete,
            search_plan=(
                self._search_plan(project_id, framing, 1, now)
                if search_ready
                else None
            ),
            corpus_gate=MedicalWritingCorpusGate(
                missing_requirements=list(self._CORPUS_REQUIREMENTS)
            ),
            created_at=now,
            updated_at=now,
            updated_by=request.actor,
        )
        state_sha256 = _payload_sha256(state.model_dump(mode="json"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT revision, state_sha256, create_request_sha256,
                       create_idempotency_key, payload_json
                FROM medical_writing_authoring_journeys WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["create_idempotency_key"] == request.idempotency_key
                    and existing["create_request_sha256"] == request_sha256
                ):
                    connection.commit()
                    return _load_authoring_journey_payload(
                        existing["payload_json"]
                    )
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "a medical-writing authoring journey already exists for this project"
                )
            connection.execute(
                """
                INSERT INTO medical_writing_authoring_journeys(
                    project_id, journey_id, revision, state_sha256,
                    create_request_sha256, create_idempotency_key,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    journey_id,
                    state_sha256,
                    request_sha256,
                    request.idempotency_key,
                    now.isoformat(),
                    now.isoformat(),
                    state.model_dump_json(),
                ),
            )
            self._insert_event(
                connection,
                state=state,
                event_type="authoring_journey_created",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={"framing_complete": framing_complete},
            )
            connection.commit()
        return state

    @staticmethod
    def _bootstrap_minimum_product_fact_packet(
        framing,
        now: datetime,
    ):
        packet = framing.minimum_product_fact_packet
        if not framing.creation_minimum_complete() or packet.status != "not_started":
            return framing

        unresolved = []
        if framing.product_profile.technology_type == "unknown":
            unresolved.append("product_profile.technology_type")
        if not framing.product_profile.administration_routes:
            unresolved.append("product_profile.administration_routes")
        if not framing.target_mechanism:
            unresolved.append("target_mechanism")

        fact_inputs = (
            ("product_identity", "framing.investigational_product", framing.investigational_product),
            ("target_indication", "framing.indication", framing.indication),
            ("study_phase", "framing.study_phase", framing.study_phase),
        )
        evidence_facts = list(framing.product_profile.evidence_facts)
        known_fact_ids = {item.fact_id for item in evidence_facts}
        evidence_facts.extend(
            MedicalWritingProductEvidenceFact(
                fact_id=fact_id,
                field_path=field_path,
                value=value,
                evidence_status="user_provided",
                confidence="high",
                user_confirmed=True,
            )
            for fact_id, field_path, value in fact_inputs
            if fact_id not in known_fact_ids
        )
        product_profile = framing.product_profile.model_copy(
            update={"evidence_facts": evidence_facts},
            deep=True,
        )
        bootstrapped_packet = MedicalWritingMinimumProductFactPacket(
            ib_status=packet.ib_status,
            ib_source_ids=list(packet.ib_source_ids),
            ib_validation_status=packet.ib_validation_status,
            ib_warning_codes=list(packet.ib_warning_codes),
            ib_override_reason=packet.ib_override_reason,
            status="sufficient_for_research",
            supporting_source_ids=list(packet.supporting_source_ids),
            unresolved_high_impact_fields=unresolved,
            safe_to_start_competitor_research=True,
            safe_to_generate_protocol_candidates=not unresolved,
            assessed_at=now,
        )
        return framing.model_copy(
            update={
                "product_profile": product_profile,
                "minimum_product_fact_packet": bootstrapped_packet,
            },
            deep=True,
        )

    def attach_synopsis_import(
        self,
        project_id: str,
        synopsis_import: MedicalWritingSynopsisImport,
        *,
        expected_revision: int,
        actor: str,
        idempotency_key: str,
    ) -> MedicalWritingAuthoringJourney:
        if synopsis_import.status != "review_pending" or synopsis_import.source is None:
            raise ValueError("synopsis import must contain a review-pending extracted source")
        synopsis_import = _capture_extracted_value_hashes(synopsis_import)
        request_payload = synopsis_import.model_dump(mode="json")
        request_sha256 = _payload_sha256(request_payload)
        replay = self._replay_from_store(project_id, idempotency_key, request_sha256)
        if replay is not None:
            return replay
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            if int(current_row["revision"]) != expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {expected_revision}, current {current_row['revision']}"
                )
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            self._ensure_reservation_allows_event(
                current, "authoring_journey_synopsis_import_attached"
            )
            if current.entry_mode != "synopsis_import":
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "the authoring journey was not started from a protocol synopsis"
                )
            if current.framing_complete or current.picos_complete:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "an imported synopsis cannot be replaced after formal study facts were completed"
                )
            now = datetime.now(timezone.utc)
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "synopsis_import": synopsis_import,
                    "study_definition": _build_study_definition(
                        project_id=project_id,
                        revision=(current.study_definition.revision + 1 if current.study_definition else 1),
                        origin="synopsis_import",
                        framing=synopsis_import.proposed_framing,
                        picos=synopsis_import.proposed_picos,
                        synopsis_import=synopsis_import,
                        confirmed_stages=set(),
                        actor=actor,
                        now=now,
                        created_at=(current.study_definition.created_at if current.study_definition else now),
                    ),
                    "framing_draft": None,
                    "picos_draft": None,
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_synopsis_import_attached",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "source_id": synopsis_import.source.source_id,
                    "content_sha256": synopsis_import.source.content_sha256,
                    "extraction_revision": synopsis_import.source.extraction_revision,
                    "missing_fields": list(synopsis_import.missing_fields),
                    "conflict_notes": list(synopsis_import.conflict_notes),
                },
            )
            connection.commit()
        return updated

    def confirm_synopsis_import(
        self,
        project_id: str,
        request: MedicalWritingSynopsisImportConfirmRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            if int(current_row["revision"]) != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current_row['revision']}"
                )
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            self._ensure_reservation_allows_event(
                current, "authoring_journey_synopsis_import_confirmed"
            )
            imported = current.synopsis_import
            if (
                current.entry_mode != "synopsis_import"
                or imported.status != "review_pending"
                or imported.source is None
                or imported.source.source_id != request.source_id
            ):
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "the current synopsis extraction is unavailable or stale"
                )
            if not imported.field_extracted_value_sha256:
                imported = _capture_extracted_value_hashes(imported)
            warnings = list(imported.source.validation_warnings)
            if warnings:
                if sorted(request.acknowledged_validation_warnings) != sorted(warnings):
                    connection.rollback()
                    raise ValueError(
                        "all current synopsis validation warnings must be acknowledged"
                    )
            now = datetime.now(timezone.utc)
            framing_draft = MedicalWritingAuthoringStageDraft(
                stage="framing",
                framing=request.framing,
                missing_required_fields=request.framing.missing_required_fields(),
                saved_from_revision=current.revision,
                saved_at=now,
                saved_by=request.actor,
            )
            picos_draft = MedicalWritingAuthoringStageDraft(
                stage="picos",
                picos=request.picos,
                missing_required_fields=request.picos.missing_required_fields(),
                saved_from_revision=current.revision,
                saved_at=now,
                saved_by=request.actor,
            )
            edited_paths = _edited_imported_fact_paths(
                imported,
                request.framing,
                request.picos,
            )
            synopsis_text = (
                _render_protocol_synopsis(
                    request.framing.model_dump(mode="json"),
                    request.picos.model_dump(mode="json"),
                )
                if edited_paths
                else request.synopsis_text
            )
            if edited_paths:
                synopsis_origin = "deterministic_projection"
            elif request.synopsis_text != imported.proposed_synopsis_text:
                synopsis_origin = "medical_manager_text"
            else:
                synopsis_origin = imported.proposed_synopsis_origin
            confirmed_import = imported.model_copy(
                update={
                    "status": "confirmed",
                    "proposed_framing": request.framing,
                    "proposed_picos": request.picos,
                    "proposed_synopsis_text": synopsis_text,
                    "proposed_synopsis_origin": synopsis_origin,
                    "synopsis_bound_value_sha256": _study_fact_value_hashes(
                        request.framing,
                        request.picos,
                    ),
                    "missing_fields": sorted(
                        {
                            *[f"framing.{item}" for item in request.framing.missing_required_fields()],
                            *[f"picos.{item}" for item in request.picos.missing_required_fields()],
                        }
                    ),
                    "confirmed_at": now,
                    "confirmed_by": request.actor,
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "stage1_in_progress",
                    "current_stage": "framing",
                    "synopsis_import": confirmed_import,
                    "framing_draft": framing_draft,
                    "picos_draft": picos_draft,
                    "study_definition": _build_study_definition(
                        project_id=project_id,
                        revision=(current.study_definition.revision + 1 if current.study_definition else 1),
                        origin="synopsis_import",
                        framing=request.framing,
                        picos=request.picos,
                        synopsis_import=confirmed_import,
                        # The medical manager's single synopsis confirmation is
                        # authoritative for every non-empty imported value.
                        # Stage completeness remains separate: genuinely
                        # missing fields stay missing and continue as drafts.
                        confirmed_stages={"framing", "picos"},
                        actor=request.actor,
                        now=now,
                        created_at=(current.study_definition.created_at if current.study_definition else now),
                    ),
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_synopsis_import_confirmed",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "source_id": request.source_id,
                    "framing_missing_fields": framing_draft.missing_required_fields,
                    "picos_missing_fields": picos_draft.missing_required_fields,
                    "medical_manager_edited_paths": edited_paths,
                    "acknowledged_validation_warnings": request.acknowledged_validation_warnings,
                    "validation_override_reason": request.validation_override_reason,
                    "formal_stages_completed": False,
                },
            )
            connection.commit()
        return updated

    def bootstrap_confirmed_legacy_import(
        self,
        project_id: str,
        imported: MedicalWritingSynopsisImport,
        request: MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
        *,
        source_origin: str,
    ) -> MedicalWritingAuthoringJourney:
        """Atomically create a journey only after an imported source is confirmed."""

        if (
            imported.status != "review_pending"
            or imported.source is None
            or imported.source.source_id != request.source_id
        ):
            raise MedicalWritingAuthoringJourneyConflictError(
                "the legacy extraction is unavailable or stale"
            )
        required_core_fields = {
            "framing.protocol_id": request.framing.protocol_id,
            "framing.version": request.framing.version,
            "framing.document_title": request.framing.document_title,
            "framing.indication": request.framing.indication,
            "framing.study_phase": request.framing.study_phase,
            "framing.investigational_product": request.framing.investigational_product,
            "framing.design_pattern": request.framing.design_pattern,
            "framing.population_intent": request.framing.population_intent,
            "picos.population_summary": request.picos.population_summary,
            "picos.intervention_summary": request.picos.intervention_summary,
            "picos.primary_endpoint": request.picos.primary_endpoint,
            "synopsis_text": request.synopsis_text,
        }
        missing_core_fields = [
            field_path
            for field_path, value in required_core_fields.items()
            if not str(value or "").strip()
        ]
        if missing_core_fields:
            raise ValueError(
                "legacy authoring bootstrap core fields must be completed before "
                "confirmation: " + ", ".join(missing_core_fields)
            )
        warnings = list(imported.source.validation_warnings)
        if warnings:
            if sorted(request.acknowledged_validation_warnings) != sorted(warnings):
                raise ValueError(
                    "all current synopsis validation warnings must be acknowledged"
                )
        imported = _capture_extracted_value_hashes(imported)
        semantic_payload = {
            "imported": imported.model_dump(mode="json"),
            "confirmation": request.model_dump(
                mode="json", exclude={"actor", "idempotency_key"}
            ),
            "source_origin": source_origin,
        }
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        edited_paths = _edited_imported_fact_paths(
            imported, request.framing, request.picos
        )
        synopsis_text = (
            _render_protocol_synopsis(
                request.framing.model_dump(mode="json"),
                request.picos.model_dump(mode="json"),
            )
            if edited_paths
            else request.synopsis_text
        )
        synopsis_origin = (
            "deterministic_projection"
            if edited_paths
            else (
                "medical_manager_text"
                if request.synopsis_text != imported.proposed_synopsis_text
                else imported.proposed_synopsis_origin
            )
        )
        confirmed_import = imported.model_copy(
            update={
                "status": "confirmed",
                "proposed_framing": request.framing,
                "proposed_picos": request.picos,
                "proposed_synopsis_text": synopsis_text,
                "proposed_synopsis_origin": synopsis_origin,
                "synopsis_bound_value_sha256": _study_fact_value_hashes(
                    request.framing, request.picos
                ),
                "missing_fields": sorted(
                    {
                        *[
                            f"framing.{item}"
                            for item in request.framing.missing_required_fields()
                        ],
                        *[
                            f"picos.{item}"
                            for item in request.picos.missing_required_fields()
                        ],
                    }
                ),
                "confirmed_at": now,
                "confirmed_by": request.actor,
            },
            deep=True,
        )
        framing_complete = not request.framing.missing_required_fields()
        picos_complete = framing_complete and not request.picos.missing_required_fields()
        if picos_complete:
            status, current_stage = "corpus_not_ready", "corpus"
        elif framing_complete:
            status, current_stage = "stage2_in_progress", "picos"
        else:
            status, current_stage = "stage1_in_progress", "framing"
        journey_id = (
            "mwjourney_"
            + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20]
        )
        study_definition = _build_study_definition(
            project_id=project_id,
            revision=1,
            origin=source_origin,
            framing=request.framing,
            picos=request.picos,
            synopsis_import=confirmed_import,
            confirmed_stages=set(),
            confirmed_paths=set(LEGACY_BOOTSTRAP_CONFIRMED_PATHS),
            actor=request.actor,
            now=now,
        )
        state = MedicalWritingAuthoringJourney(
            journey_id=journey_id,
            project_id=project_id,
            revision=1,
            entry_mode="synopsis_import",
            synopsis_import=confirmed_import,
            study_definition=study_definition,
            status=status,
            current_stage=current_stage,
            framing=request.framing,
            picos=request.picos,
            framing_draft=(
                None
                if framing_complete
                else MedicalWritingAuthoringStageDraft(
                    stage="framing",
                    framing=request.framing,
                    missing_required_fields=request.framing.missing_required_fields(),
                    saved_from_revision=1,
                    saved_at=now,
                    saved_by=request.actor,
                )
            ),
            picos_draft=(
                None
                if picos_complete
                else MedicalWritingAuthoringStageDraft(
                    stage="picos",
                    picos=request.picos,
                    missing_required_fields=request.picos.missing_required_fields(),
                    saved_from_revision=1,
                    saved_at=now,
                    saved_by=request.actor,
                )
            ),
            framing_complete=framing_complete,
            picos_complete=picos_complete,
            search_plan=(
                self._search_plan(project_id, request.framing, 1, now)
                if request.framing.creation_minimum_complete()
                else None
            ),
            corpus_gate=MedicalWritingCorpusGate(
                missing_requirements=list(self._CORPUS_REQUIREMENTS)
            ),
            created_at=now,
            updated_at=now,
            updated_by=request.actor,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT create_request_sha256, create_idempotency_key, payload_json
                FROM medical_writing_authoring_journeys WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["create_idempotency_key"] == request.idempotency_key
                    and existing["create_request_sha256"] == request_sha256
                ):
                    connection.commit()
                    return _load_authoring_journey_payload(
                        existing["payload_json"]
                    )
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "a medical-writing authoring journey already exists for this project"
                )
            connection.execute(
                """
                INSERT INTO medical_writing_authoring_journeys(
                    project_id, journey_id, revision, state_sha256,
                    create_request_sha256, create_idempotency_key,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    journey_id,
                    _payload_sha256(state.model_dump(mode="json")),
                    request_sha256,
                    request.idempotency_key,
                    now.isoformat(),
                    now.isoformat(),
                    state.model_dump_json(),
                ),
            )
            self._insert_event(
                connection,
                state=state,
                event_type="authoring_journey_legacy_bootstrap_confirmed",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "source_id": imported.source.source_id,
                    "source_sha256": imported.source.content_sha256,
                    "source_origin": source_origin,
                    "confirmed_paths": sorted(LEGACY_BOOTSTRAP_CONFIRMED_PATHS),
                    "medical_manager_edited_paths": edited_paths,
                    "acknowledged_validation_warnings": (
                        request.acknowledged_validation_warnings
                    ),
                    "validation_override_reason": request.validation_override_reason,
                    "source_role_override_reason": request.source_role_override_reason,
                },
            )
            connection.commit()
        return state

    def get(self, project_id: str) -> MedicalWritingAuthoringJourney:
        with self._connect() as connection:
            row = self._current_row(connection, project_id)
        return _load_authoring_journey_payload(row["payload_json"])

    def save_research_pipeline(
        self, project_id: str, pipeline: dict[str, Any]
    ) -> MedicalWritingAuthoringJourney:
        """Persist research pipeline projection without advancing authoring stages.

        Deliberately does NOT bump ``revision``: the pipeline's own progress
        projection is a system-owned side channel, not authoring content.
        Competitor-triage staleness (``CompetitorTriageService._stale_reason``
        / ``_material_facts_hash``) keys off ``journey.revision`` (and embeds
        it directly) to detect real authoring-content changes (framing/PICOS/
        product profile) between a triage run's creation and its confirmation.
        If every research-pipeline progress write bumped that same counter,
        a triage run created earlier in the same pipeline execution would be
        spuriously marked stale by the time ``confirm_basket`` runs later in
        that same execution — even though nothing relevant actually changed —
        causing ``confirm_basket`` to fail and the pipeline to fall back to a
        much weaker legacy path that finds no pre-existing relevance
        decisions and reports "no retainable candidates".
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(row["payload_json"])
            incoming_pipeline = dict(pipeline or {})
            current_pipeline = dict(
                getattr(current, "research_pipeline", None) or {}
            )

            # Research-pipeline progress is an opaque side channel written by
            # both the durable worker and read-only status refreshes.  A stale
            # request must never roll a continuation back to an earlier job or
            # child batch.  New pipeline identities are accepted only when
            # their creation timestamp is newer (force/restart); writes within
            # one identity use the monotonic generation emitted by the service.
            incoming_pipeline_id = str(incoming_pipeline.get("pipeline_id") or "")
            current_pipeline_id = str(current_pipeline.get("pipeline_id") or "")
            if current_pipeline and incoming_pipeline_id != current_pipeline_id:
                incoming_created = str(incoming_pipeline.get("created_at") or "")
                current_created = str(current_pipeline.get("created_at") or "")
                if current_created and (
                    not incoming_created or incoming_created <= current_created
                ):
                    connection.commit()
                    return current
            elif current_pipeline_id and incoming_pipeline_id == current_pipeline_id:
                try:
                    incoming_generation = int(
                        incoming_pipeline.get("write_generation") or 0
                    )
                except (TypeError, ValueError):
                    incoming_generation = 0
                try:
                    current_generation = int(
                        current_pipeline.get("write_generation") or 0
                    )
                except (TypeError, ValueError):
                    current_generation = 0
                if incoming_generation <= current_generation:
                    connection.commit()
                    return current
            expected_revision = current.revision
            now = datetime.now(timezone.utc)
            updated = current.model_copy(
                update={
                    "updated_at": now,
                    "updated_by": "research_pipeline",
                    "research_pipeline": incoming_pipeline,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                state=updated,
                expected_revision=expected_revision,
                event_type="research_pipeline_progress",
                actor="research_pipeline",
                idempotency_key=(
                    "pipe-"
                    + str(incoming_pipeline.get("pipeline_id") or project_id)
                    + "-"
                    + str(incoming_pipeline.get("stage") or "unknown")
                    + "-"
                    + str(incoming_pipeline.get("updated_at") or now.isoformat())
                )[:200],
                request_sha256=_payload_sha256(
                    {
                        "pipeline_id": incoming_pipeline.get("pipeline_id"),
                        "stage": incoming_pipeline.get("stage"),
                        "percent": incoming_pipeline.get("percent"),
                        "updated_at": incoming_pipeline.get("updated_at"),
                    }
                ),
                detail={
                    "stage": incoming_pipeline.get("stage"),
                    "percent": incoming_pipeline.get("percent"),
                },
            )
            connection.commit()
            return updated

    def impact_preview(
        self,
        project_id: str,
        request: MedicalWritingJourneyImpactPreviewRequest,
    ) -> MedicalWritingJourneyImpactPreview:
        state = self.get(project_id)
        if request.expected_revision != state.revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {request.expected_revision}, current {state.revision}"
            )
        current = state.framing if request.stage == "framing" else state.picos
        proposed = request.framing if request.stage == "framing" else request.picos
        assert proposed is not None
        changed_fields = _changed_fields(
            request.stage,
            current.model_dump(mode="json"),
            proposed.model_dump(mode="json"),
        )
        dependents = sorted(
            {
                dependent
                for field_name in changed_fields
                for dependent in self._IMPACT_MAP.get(field_name, [])
            }
        )
        downstream_exists = (
            state.search_plan is not None
            if request.stage == "framing"
            else state.picos_complete or state.current_stage in {"corpus", "writing"}
        )
        preview_payload = {
            "project_id": project_id,
            "expected_revision": state.revision,
            "stage": request.stage,
            "changed_fields": changed_fields,
            "affected_dependents": dependents,
        }
        return MedicalWritingJourneyImpactPreview(
            preview_id="mwimpact_" + _payload_sha256(preview_payload)[:24],
            project_id=project_id,
            expected_revision=state.revision,
            stage=request.stage,
            changed_fields=changed_fields,
            affected_dependents=dependents,
            requires_confirmation=bool(changed_fields and dependents and downstream_exists),
        )

    def _carry_forward_corpus_gate(self, current) -> MedicalWritingCorpusGate:
        """Rebuild the corpus gate for a stage commit.

        Requirements-v2 R3: an active override stays valid across requirement
        changes, so the rebuilt gate keeps the writing access the override
        already granted instead of silently re-blocking the author.  The
        override object is always carried as-is: ``None`` is not a valid
        MedicalWritingCorpusGateOverride instance, and passing it crashed
        every fresh-project commit at step one (round-5 P0).
        """
        if current.corpus_gate is not None and current.corpus_gate.override is not None:
            override = current.corpus_gate.override
        else:
            override = MedicalWritingCorpusGateOverride()
        return MedicalWritingCorpusGate(
            missing_requirements=list(self._CORPUS_REQUIREMENTS),
            override=override,
            access_permitted=bool(override.active),
        )

    def commit_stage(
        self,
        project_id: str,
        request: MedicalWritingAuthoringJourneyCommitRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        preview = self.impact_preview(project_id, request)
        if preview.requires_confirmation and request.impact_preview_id != preview.preview_id:
            raise MedicalWritingAuthoringJourneyConflictError(
                "authoring journey change requires the current impact preview to be confirmed"
            )
        state = self.get(project_id)
        if request.stage == "picos" and not state.framing_complete:
            raise ValueError("study framing must be complete before PICOS can be committed")
        proposed = request.framing if request.stage == "framing" else request.picos
        assert proposed is not None
        missing_required_fields = proposed.missing_required_fields()
        if missing_required_fields:
            raise ValueError(
                f"{request.stage} cannot be completed; missing required fields: "
                + ", ".join(missing_required_fields)
            )
        if not preview.changed_fields:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                replay = self._idempotent_replay(
                    connection, project_id, request.idempotency_key, request_sha256
                )
                if replay is not None:
                    connection.commit()
                    return replay
                current_row = self._current_row(connection, project_id)
                if int(current_row["revision"]) != request.expected_revision:
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        f"stale authoring journey revision: expected {request.expected_revision}, current {current_row['revision']}"
                    )
                current = _load_authoring_journey_payload(
                    current_row["payload_json"]
                )
                self._ensure_reservation_allows_event(
                    current, f"authoring_journey_{request.stage}_commit_noop"
                )
                # An upstream framing commit can invalidate the formal PICOS
                # completion flag while retaining the exact same committed
                # PICOS values.  A subsequent visible "完成第二步" then has
                # no field diff, but it is still a meaningful state
                # transition: recompute the completion gate and rebuild the
                # versioned StudyDefinition instead of returning the stale
                # incomplete state as a no-op.  The same reconcile also
                # repairs a definition whose committed PICOS facts were
                # demoted to manual candidates while the completion flag
                # stayed true — such a formal/field-state split blocks all
                # downstream fact-bound writing.
                picos_states_demoted = (
                    current.study_definition is not None
                    and any(
                        state.status in {"manual_candidate", "extracted_candidate"}
                        for path, state in current.study_definition.field_states.items()
                        if path.startswith("picos.")
                    )
                )
                if request.stage == "picos" and (
                    not current.picos_complete or picos_states_demoted
                ):
                    now = datetime.now(timezone.utc)
                    updated = current.model_copy(
                        update={
                            "revision": current.revision + 1,
                            "picos": request.picos,
                            "picos_draft": None,
                            "picos_complete": True,
                            "status": "corpus_not_ready",
                            "current_stage": "corpus",
                            "corpus_gate": self._carry_forward_corpus_gate(current),
                            "picos_corpus_alignment": MedicalWritingPicosCorpusAlignment(),
                            "updated_at": now,
                            "updated_by": request.actor,
                        },
                        deep=True,
                    )
                    updated = updated.model_copy(
                        update={
                            "study_definition": _build_study_definition(
                                project_id=project_id,
                                revision=(
                                    current.study_definition.revision + 1
                                    if current.study_definition
                                    else 1
                                ),
                                origin=current.entry_mode,
                                framing=current.framing,
                                picos=request.picos,
                                synopsis_import=current.synopsis_import,
                                confirmed_stages={"framing", "picos"},
                                actor=request.actor,
                                now=now,
                                created_at=(
                                    current.study_definition.created_at
                                    if current.study_definition
                                    else now
                                ),
                                current_study_schema=(
                                    current.study_definition.study_schema
                                    if current.study_definition
                                    else None
                                ),
                            )
                        },
                        deep=True,
                    )
                    self._persist_update(
                        connection,
                        updated,
                        expected_revision=current.revision,
                        event_type="authoring_journey_picos_completion_reconciled",
                        actor=request.actor,
                        idempotency_key=request.idempotency_key,
                        request_sha256=request_sha256,
                        detail={
                            "changed_fields": [],
                            "formal_state_reconciled": True,
                            "picos_complete": True,
                        },
                    )
                    connection.commit()
                    return updated
                draft_field = f"{request.stage}_draft"
                if getattr(current, draft_field) is None:
                    self._insert_event(
                        connection,
                        state=current,
                        event_type=f"authoring_journey_{request.stage}_commit_noop",
                        actor=request.actor,
                        idempotency_key=request.idempotency_key,
                        request_sha256=request_sha256,
                        detail={"changed_fields": [], "state_unchanged": True},
                    )
                    connection.commit()
                    return current
                now = datetime.now(timezone.utc)
                updated = current.model_copy(
                    update={
                        "revision": current.revision + 1,
                        draft_field: None,
                        "updated_at": now,
                        "updated_by": request.actor,
                    },
                    deep=True,
                )
                self._persist_update(
                    connection,
                    updated,
                    expected_revision=current.revision,
                    event_type=f"authoring_journey_{request.stage}_draft_promoted_noop",
                    actor=request.actor,
                    idempotency_key=request.idempotency_key,
                    request_sha256=request_sha256,
                    detail={"changed_fields": [], "formal_state_unchanged": True},
                )
                connection.commit()
            return updated
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            if int(current_row["revision"]) != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current_row['revision']}"
                )
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            now = datetime.now(timezone.utc)
            revision = current.revision + 1
            invalidated = sorted(
                set(current.invalidated_dependents) | set(preview.affected_dependents)
            )
            if request.stage == "framing":
                assert request.framing is not None
                framing_complete = not request.framing.missing_required_fields()
                search_ready = request.framing.creation_minimum_complete()
                updates: dict[str, Any] = {
                    "revision": revision,
                    "framing": request.framing,
                    "framing_draft": None,
                    "framing_complete": framing_complete,
                    "status": "stage1_complete" if framing_complete else "stage1_in_progress",
                    "current_stage": "picos" if framing_complete else "framing",
                    "search_plan": (
                        self._search_plan(project_id, request.framing, revision, now)
                        if search_ready
                        else None
                    ),
                    "invalidated_dependents": invalidated,
                    "updated_at": now,
                    "updated_by": request.actor,
                }
                updates["study_definition"] = _build_study_definition(
                    project_id=project_id,
                    revision=(current.study_definition.revision + 1 if current.study_definition else 1),
                    origin=current.entry_mode,
                    framing=request.framing,
                    picos=(current.picos_draft.picos if current.picos_draft else current.picos),
                    synopsis_import=current.synopsis_import,
                    # Confirming a file-first synopsis is one medical-manager
                    # decision over both extracted stages. Promoting the
                    # framing stage must not demote its non-empty PICOS facts
                    # back to extracted candidates merely because PICOS still
                    # has genuinely missing fields.  The same protection keeps
                    # committed PICOS facts confirmed when this framing change
                    # does not require re-confirmation of the PICOS stage:
                    # only an invalidating framing edit may demote them.
                    confirmed_stages=(
                        {"framing", "picos"}
                        if (
                            (
                                current.entry_mode == "synopsis_import"
                                and current.synopsis_import.status == "confirmed"
                                and current.picos_draft is not None
                            )
                            or (
                                bool(current.picos_complete)
                                and not preview.requires_confirmation
                            )
                        )
                        else {"framing"}
                    ),
                    actor=request.actor,
                    now=now,
                    created_at=(current.study_definition.created_at if current.study_definition else now),
                    current_study_schema=(
                        current.study_definition.study_schema
                        if current.study_definition
                        else None
                    ),
                )
                if preview.requires_confirmation:
                    updates.update(
                        {
                            "picos_complete": False,
                            # An upstream change invalidates committed downstream
                            # conclusions, but an uncommitted PICOS draft is user
                            # work. Keep it visible for review instead of forcing
                            # the author to recreate imported or edited content.
                            "picos_draft": current.picos_draft,
                            "corpus_gate": self._carry_forward_corpus_gate(current),
                            "corpus_triage": MedicalWritingCorpusTriage(),
                            "picos_corpus_alignment": MedicalWritingPicosCorpusAlignment(),
                        }
                    )
            else:
                assert request.picos is not None
                picos_complete = not request.picos.missing_required_fields()
                updates = {
                    "revision": revision,
                    "picos": request.picos,
                    "picos_draft": None,
                    "picos_complete": picos_complete,
                    "status": "corpus_not_ready" if picos_complete else "stage2_in_progress",
                    "current_stage": "corpus" if picos_complete else "picos",
                    "corpus_gate": self._carry_forward_corpus_gate(current),
                    "picos_corpus_alignment": MedicalWritingPicosCorpusAlignment(),
                    "invalidated_dependents": invalidated,
                    "updated_at": now,
                    "updated_by": request.actor,
                }
                updates["study_definition"] = _build_study_definition(
                    project_id=project_id,
                    revision=(current.study_definition.revision + 1 if current.study_definition else 1),
                    origin=current.entry_mode,
                    framing=current.framing,
                    picos=request.picos,
                    synopsis_import=current.synopsis_import,
                    confirmed_stages={"framing", "picos"},
                    actor=request.actor,
                    now=now,
                    created_at=(current.study_definition.created_at if current.study_definition else now),
                    current_study_schema=(
                        current.study_definition.study_schema
                        if current.study_definition
                        else None
                    ),
                )
            if "study_schema" in preview.affected_dependents:
                updates["study_schema_presentation"] = None
            updated = current.model_copy(update=updates, deep=True)
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type=f"authoring_journey_{request.stage}_committed",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "changed_fields": preview.changed_fields,
                    "affected_dependents": preview.affected_dependents,
                    "impact_preview_id": preview.preview_id,
                },
            )
            connection.commit()
        return updated

    def save_stage_draft(
        self,
        project_id: str,
        request: MedicalWritingAuthoringJourneyDraftSaveRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        state = self.get(project_id)
        if request.expected_revision != state.revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {request.expected_revision}, current {state.revision}"
            )
        if request.stage == "picos" and not state.framing_complete:
            raise ValueError("study framing must be complete before a PICOS draft can be saved")
        payload = request.framing if request.stage == "framing" else request.picos
        assert payload is not None
        missing_required_fields = payload.missing_required_fields()
        now = datetime.now(timezone.utc)
        draft = MedicalWritingAuthoringStageDraft(
            stage=request.stage,
            framing=request.framing if request.stage == "framing" else None,
            picos=request.picos if request.stage == "picos" else None,
            missing_required_fields=missing_required_fields,
            saved_from_revision=state.revision,
            saved_at=now,
            saved_by=request.actor,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            if int(current_row["revision"]) != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current_row['revision']}"
                )
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            state_updates: dict[str, Any] = {
                "revision": current.revision + 1,
                f"{request.stage}_draft": draft,
                "updated_at": now,
                "updated_by": request.actor,
            }
            search_plan_action = "unchanged"
            if request.stage == "framing" and not current.framing_complete:
                assert request.framing is not None
                # A framing draft may unlock broad competitor research with the
                # three user-supplied search facts. Keep every other draft fact
                # uncommitted until the formal framing-stage confirmation.
                search_framing = request.framing
                if search_framing.creation_minimum_complete():
                    candidate_plan = self._search_plan(
                        project_id,
                        search_framing,
                        current.revision + 1,
                        now,
                    )
                    if (
                        current.search_plan is not None
                        and current.search_plan.registry_filter
                        == candidate_plan.registry_filter
                    ):
                        state_updates["search_plan"] = current.search_plan
                        search_plan_action = "preserved"
                    else:
                        state_updates["search_plan"] = candidate_plan
                        search_plan_action = "created_or_rebuilt"
                else:
                    state_updates["search_plan"] = None
                    search_plan_action = "blocked_missing_creation_minimum"
            updated = current.model_copy(
                update=state_updates,
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type=f"authoring_journey_{request.stage}_draft_saved",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "missing_required_fields": missing_required_fields,
                    "completion_state_unchanged": True,
                    "downstream_invalidated": False,
                    "competitor_search_plan": search_plan_action,
                },
            )
            connection.commit()
        return updated

    def picos_sha256(self, project_id: str) -> str:
        state = self.get(project_id)
        return _payload_sha256(state.picos.model_dump(mode="json"))

    def study_schema_snapshot(self, project_id: str) -> MedicalWritingStudySchemaSnapshot:
        state = self.get(project_id)
        definition = state.study_definition
        if definition is None:
            raise ValueError("the project has no versioned StudyDefinition")
        schema = definition.study_schema
        presentation = state.study_schema_presentation
        if schema is None:
            return MedicalWritingStudySchemaSnapshot(
                project_id=project_id,
                journey_revision=state.revision,
                study_definition_revision=definition.revision,
                study_definition_sha256=definition.state_sha256,
            )
        current_facts_sha256 = _study_definition_facts_sha256(
            definition.framing, definition.picos
        )
        if schema.source_facts_sha256 != current_facts_sha256:
            schema = schema.model_copy(update={"status": "stale"}, deep=True)
            schema = schema.model_copy(
                update={"state_sha256": study_schema_state_sha256(schema)}, deep=True
            )
        if presentation is not None and (
            presentation.schema_id != schema.schema_id
            or presentation.schema_revision != schema.revision
            or presentation.source_schema_sha256 != schema.state_sha256
        ):
            presentation = None
        issues = validate_study_schema(schema)
        svg = render_study_schema_svg(schema, presentation)
        return MedicalWritingStudySchemaSnapshot(
            project_id=project_id,
            journey_revision=state.revision,
            study_definition_revision=definition.revision,
            study_definition_sha256=definition.state_sha256,
            study_schema=schema,
            presentation=presentation,
            issues=issues,
            formal_render_allowed=formal_render_allowed(schema, issues),
            svg_sha256=hashlib.sha256(svg.encode("utf-8")).hexdigest(),
            svg=svg,
        )

    def propose_study_schema(
        self, project_id: str
    ) -> MedicalWritingStudySchemaDefinition:
        state = self.get(project_id)
        definition = state.study_definition
        if definition is None or not state.framing_complete or not state.picos_complete:
            raise ValueError(
                "framing and PICOS must be formally complete before proposing the study schema"
            )
        # Design-driven flowchart proposal requires a confirmed current plan.
        _, design_projection = self._require_study_schema_design_projection(
            definition
        )
        framing = definition.framing
        picos = definition.picos
        facts_sha256 = _study_definition_facts_sha256(framing, picos)
        if (
            definition.study_schema is not None
            and definition.study_schema.status != "stale"
            and definition.study_schema.source_facts_sha256 == facts_sha256
        ):
            return definition.study_schema
        now = datetime.now(timezone.utc)

        def binding(path: str) -> list[MedicalWritingStudySchemaSourceBinding]:
            return [
                MedicalWritingStudySchemaSourceBinding(study_definition_path=path)
            ]

        phase1_modules = _study_schema_phase1_modules(design_projection)
        if phase1_modules:
            proposal = _propose_phase1_study_schema(
                project_id=project_id,
                framing=framing,
                picos=picos,
                design_projection=design_projection,
                facts_sha256=facts_sha256,
                modules=phase1_modules,
                now=now,
            )
            return proposal.model_copy(
                update={"state_sha256": study_schema_state_sha256(proposal)}, deep=True
            )
        if design_projection.design_view.crossover.planned is True:
            proposal = _propose_crossover_study_schema(
                project_id=project_id,
                picos=picos,
                design_projection=design_projection,
                facts_sha256=facts_sha256,
                now=now,
            )
            return proposal.model_copy(
                update={"state_sha256": study_schema_state_sha256(proposal)},
                deep=True,
            )

        parts = [
            MedicalWritingStudySchemaPart(
                part_id="main",
                order=0,
                label="总体研究流程",
                flow_direction="left_to_right",
                source_bindings=binding("picos.study_epochs"),
            )
        ]
        nodes: list[MedicalWritingStudySchemaNode] = []
        edges: list[MedicalWritingStudySchemaEdge] = []
        design_view = design_projection.design_view
        randomized = design_view.randomization_mode == "randomized"
        epochs = picos.study_epochs or ["筛选期", "治疗期", "安全性随访期"]
        nodes.append(
            MedicalWritingStudySchemaNode(
                node_id="epoch_0",
                part_id="main",
                order=0,
                node_kind=_study_schema_epoch_kind(epochs[0], first=True),
                label=epochs[0],
                fact_status="extracted_candidate",
                source_bindings=binding("picos.study_epochs.0"),
            )
        )
        prior_ids = ["epoch_0"]
        randomized_arm_ids: list[str] = []
        next_order = 1
        if randomized:
            nodes.append(
                MedicalWritingStudySchemaNode(
                    node_id="randomization",
                    part_id="main",
                    order=next_order,
                    node_kind="randomization",
                    label="随机分配",
                    detail_lines=[
                        item
                        for item in (
                            design_view.randomization_details,
                            design_view.assignment_model,
                        )
                        if item
                    ],
                    fact_status="extracted_candidate",
                    source_bindings=binding(
                        "framing.structured_design.randomization_mode"
                    ),
                )
            )
            edges.append(
                MedicalWritingStudySchemaEdge(
                    edge_id="edge_0_randomization",
                    from_node_id="epoch_0",
                    to_node_id="randomization",
                    fact_status="extracted_candidate",
                    source_bindings=binding(
                        "framing.structured_design.randomization_mode"
                    ),
                )
            )
            next_order += 1
            prior_ids = []
            for node_id, lane_order, label, detail, path in (
                (
                    "intervention",
                    0,
                    "研究干预",
                    "；".join(
                        item
                        for item in (
                            picos.intervention_summary,
                            *(
                                getattr(
                                    picos, "required_background_rules", []
                                )
                                or []
                            ),
                        )
                        if item
                    ),
                    "picos.intervention_summary",
                ),
                (
                    "comparator",
                    1,
                    "对照",
                    picos.comparator_summary,
                    "picos.comparator_summary",
                ),
            ):
                if not detail:
                    continue
                nodes.append(
                    MedicalWritingStudySchemaNode(
                        node_id=node_id,
                        part_id="main",
                        order=next_order,
                        lane_order=lane_order,
                        node_kind="arm",
                        label=label,
                        detail_lines=[detail[:120]],
                        fact_status="extracted_candidate",
                        source_bindings=binding(path),
                    )
                )
                edges.append(
                    MedicalWritingStudySchemaEdge(
                        edge_id=f"edge_randomization_{node_id}",
                        from_node_id="randomization",
                        to_node_id=node_id,
                        edge_kind="randomization",
                        fact_status="extracted_candidate",
                        source_bindings=binding(
                            "framing.structured_design.randomization_mode"
                        ),
                    )
                )
                prior_ids.append(node_id)
                randomized_arm_ids.append(node_id)
            next_order += 1

        remaining_epochs = epochs[1:] if len(epochs) > 1 else ["安全性随访期"]

        def insert_before_follow_up(label: str) -> None:
            follow_index = next(
                (
                    index
                    for index, item in enumerate(remaining_epochs)
                    if _study_schema_epoch_kind(item) == "follow_up"
                ),
                len(remaining_epochs),
            )
            remaining_epochs.insert(follow_index, label)

        if (
            design_view.treatment_switch.planned is True
            and not any(
                _study_schema_epoch_kind(item) == "treatment_switch"
                for item in remaining_epochs
            )
        ):
            insert_before_follow_up(
                design_view.treatment_switch.trigger_or_timing or "治疗切换"
            )
        if (
            design_view.open_label_extension.planned is True
            and not any(
                _study_schema_epoch_kind(item) == "extension_period"
                for item in remaining_epochs
            )
        ):
            insert_before_follow_up(
                "开放标签延展"
                + (
                    f"（{design_view.open_label_extension.duration}）"
                    if design_view.open_label_extension.duration
                    else ""
                )
            )
        if design_view.interim_analysis.planned is True:
            insert_before_follow_up(
                "期中分析："
                + (
                    design_view.interim_analysis.timing
                    or design_view.interim_analysis.information_fraction
                )
            )
        if design_view.adaptive_design.planned is True:
            insert_before_follow_up(
                "适应性决策："
                + (
                    design_view.adaptive_design.adaptation_timing
                    or design_view.adaptive_design.adaptive_type
                )
            )
        if design_view.sample_size_reestimation.planned is True:
            reestimation = design_view.sample_size_reestimation
            mode = (
                "盲态"
                if reestimation.reestimation_mode == "blinded"
                else "非盲态"
            )
            insert_before_follow_up(
                f"{mode}样本量再估计：{reestimation.timing_or_information}"
            )
        if design_view.src_planned is True:
            insert_before_follow_up("SRC安全性审查")
        if design_view.dmc_planned is True:
            insert_before_follow_up("DMC数据监查")
        transition_kinds = {
            _study_schema_epoch_kind(label) for label in remaining_epochs
        }
        has_transition_design = bool(
            randomized
            and transition_kinds.intersection(
                {"treatment_switch", "extension_period"}
            )
        )
        if has_transition_design:
            first_transition_index = next(
                (
                    index
                    for index, label in enumerate(remaining_epochs)
                    if _study_schema_epoch_kind(label)
                    in {"treatment_switch", "extension_period"}
                ),
                len(remaining_epochs),
            )
            ordinary_treatment_epochs = [
                label
                for index, label in enumerate(remaining_epochs)
                if index < first_transition_index
                and _study_schema_epoch_kind(label) in {"treatment", "other"}
            ]
            if ordinary_treatment_epochs:
                for node in nodes:
                    if node.node_id in randomized_arm_ids:
                        node.detail_lines = [
                            *node.detail_lines,
                            *(
                                label
                                for label in ordinary_treatment_epochs
                            ),
                        ]
                remaining_epochs = [
                    label
                    for index, label in enumerate(remaining_epochs)
                    if not (
                        index < first_transition_index
                        and _study_schema_epoch_kind(label)
                        in {"treatment", "other"}
                    )
                ]
        switch_explicit = design_view.treatment_switch.planned is True
        for epoch_index, label in enumerate(remaining_epochs, start=1):
            node_id = f"epoch_{epoch_index}"
            node_kind = _study_schema_epoch_kind(
                label, last=epoch_index == len(remaining_epochs)
            )
            source_path = f"picos.study_epochs.{epoch_index}"
            detail_lines: list[str] = []
            if (
                node_kind == "treatment_switch"
                and design_view.treatment_switch.planned is True
            ):
                source_path = "framing.structured_design.treatment_switch"
                detail_lines = [
                    design_view.treatment_switch.eligible_population,
                    "转入" + design_view.treatment_switch.destination_treatment,
                    design_view.treatment_switch.blinding_strategy,
                ]
            elif (
                node_kind == "extension_period"
                and design_view.open_label_extension.planned is True
            ):
                source_path = "framing.structured_design.open_label_extension"
                detail_lines = [
                    design_view.open_label_extension.entry_eligibility,
                    design_view.open_label_extension.treatment_regimen,
                    design_view.open_label_extension.duration,
                ]
            elif label.startswith("期中分析："):
                node_kind = "decision_gate"
                source_path = "framing.structured_design.interim_analysis"
                detail_lines = [
                    design_view.interim_analysis.purpose,
                    design_view.interim_analysis.statistical_boundary,
                ]
            elif label.startswith("适应性决策："):
                node_kind = "decision_gate"
                source_path = "framing.structured_design.adaptive_design"
                detail_lines = [
                    design_view.adaptive_design.decision_criteria,
                    design_view.adaptive_design.type_i_error_control,
                ]
            elif "样本量再估计：" in label:
                node_kind = "decision_gate"
                source_path = (
                    "framing.structured_design.sample_size_reestimation"
                )
                detail_lines = [
                    design_view.sample_size_reestimation.reestimated_parameter,
                    design_view.sample_size_reestimation.decision_rule,
                    design_view.sample_size_reestimation.operational_protection,
                ]
            elif label == "SRC安全性审查":
                node_kind = "decision_gate"
                source_path = "framing.structured_design.src_planned"
            elif label == "DMC数据监查":
                node_kind = "decision_gate"
                source_path = "framing.structured_design.dmc_planned"
            nodes.append(
                MedicalWritingStudySchemaNode(
                    node_id=node_id,
                    part_id="main",
                    order=next_order,
                    node_kind=node_kind,
                    label=label,
                    detail_lines=[item for item in detail_lines if item],
                    fact_status="extracted_candidate",
                    source_bindings=binding(source_path),
                )
            )
            if node_kind == "treatment_switch" and randomized_arm_ids:
                for prior_id in randomized_arm_ids:
                    is_comparator = prior_id == "comparator"
                    edges.append(
                        MedicalWritingStudySchemaEdge(
                            edge_id=f"edge_{prior_id}_{node_id}",
                            from_node_id=prior_id,
                            to_node_id=node_id,
                            edge_kind=(
                                "treatment_switch"
                                if is_comparator
                                else "treatment_continuation"
                            ),
                            label=(
                                "转组治疗"
                                if is_comparator
                                else "继续治疗"
                            ),
                            fact_status="extracted_candidate",
                            source_bindings=binding(
                                "picos.comparator_summary"
                                if is_comparator
                                else "picos.intervention_summary"
                            ),
                        )
                    )
                prior_ids = [node_id]
                next_order += 1
                continue
            if (
                node_kind == "extension_period"
                and set(prior_ids) == set(randomized_arm_ids)
            ):
                for prior_id in prior_ids:
                    is_comparator = prior_id == "comparator"
                    if switch_explicit:
                        edge_kind = (
                            "treatment_switch"
                            if is_comparator
                            else "treatment_continuation"
                        )
                        edge_label = (
                            "转组治疗"
                            if is_comparator
                            else "继续治疗"
                        )
                        edge_status = "extracted_candidate"
                    else:
                        edge_kind = "conditional"
                        edge_label = "延展期治疗方式待确认"
                        edge_status = "missing"
                    edges.append(
                        MedicalWritingStudySchemaEdge(
                            edge_id=f"edge_{prior_id}_{node_id}",
                            from_node_id=prior_id,
                            to_node_id=node_id,
                            edge_kind=edge_kind,
                            label=edge_label,
                            fact_status=edge_status,
                            source_bindings=binding(
                                "picos.comparator_summary"
                                if is_comparator
                                else "picos.intervention_summary"
                            ),
                        )
                    )
                prior_ids = [node_id]
                next_order += 1
                continue
            for prior_id in prior_ids:
                edges.append(
                    MedicalWritingStudySchemaEdge(
                        edge_id=f"edge_{prior_id}_{node_id}",
                        from_node_id=prior_id,
                        to_node_id=node_id,
                        edge_kind=("follow_up" if node_kind == "follow_up" else "participant_flow"),
                        fact_status="extracted_candidate",
                        source_bindings=binding("picos.study_epochs"),
                    )
                )
            prior_ids = [node_id]
            next_order += 1

        proposal = MedicalWritingStudySchemaDefinition(
            schema_id="mwschema_proposal_" + hashlib.sha256(
                project_id.encode("utf-8")
            ).hexdigest()[:20],
            revision=1,
            source_facts_sha256=facts_sha256,
            status="draft",
            title="研究设计概况",
            parts=parts,
            nodes=nodes,
            edges=edges,
            annotations=["本图由已确认研究框架与PICOS生成，所有候选节点和关系须经医学确认。"],
            state_sha256="0" * 64,
            updated_at=now,
            updated_by="system_proposal",
        )
        return proposal.model_copy(
            update={"state_sha256": study_schema_state_sha256(proposal)}, deep=True
        )

    def study_schema_impact_preview(
        self,
        project_id: str,
        request: MedicalWritingStudySchemaImpactPreviewRequest,
    ) -> MedicalWritingStudySchemaImpactPreview:
        state = self.get(project_id)
        if state.revision != request.expected_journey_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                "stale authoring journey revision: "
                f"expected {request.expected_journey_revision}, current {state.revision}"
            )
        definition = state.study_definition
        if definition is None or not state.framing_complete or not state.picos_complete:
            raise ValueError(
                "framing and PICOS must be formally complete before editing the study schema"
            )
        # Impact validation must consume the same confirmed flowchart projection.
        self._align_schema_with_plan(project_id, request.study_schema)
        current_facts_sha256 = _study_definition_facts_sha256(
            definition.framing, definition.picos
        )
        if request.study_schema.source_facts_sha256 != current_facts_sha256:
            raise MedicalWritingAuthoringJourneyConflictError(
                "study-schema proposal is not bound to the current StudyDefinition facts"
            )
        current_payload = (
            _study_schema_comparison_payload(definition.study_schema)
            if definition.study_schema is not None
            else {}
        )
        proposed_payload = _study_schema_comparison_payload(request.study_schema)
        changed_fields = _changed_fields(
            "study_schema", current_payload, proposed_payload
        )
        affected = (
            [
                "protocol_synopsis",
                "study_schema",
                "schedule_of_activities",
                "document_figure",
                "figure_index",
            ]
            if changed_fields
            else []
        )
        issues = validate_study_schema(request.study_schema)
        svg = render_study_schema_svg(request.study_schema)
        preview_payload = {
            "project_id": project_id,
            "expected_journey_revision": state.revision,
            "proposed_schema_sha256": canonical_payload_sha256(proposed_payload),
            "changed_fields": changed_fields,
            "affected_dependents": affected,
        }
        return MedicalWritingStudySchemaImpactPreview(
            preview_id="mwschema_impact_" + _payload_sha256(preview_payload)[:24],
            project_id=project_id,
            expected_journey_revision=state.revision,
            changed_fields=changed_fields,
            affected_dependents=affected,
            issues=issues,
            requires_confirmation=bool(changed_fields),
            formal_render_allowed=formal_render_allowed(request.study_schema, issues),
            svg_sha256=hashlib.sha256(svg.encode("utf-8")).hexdigest(),
            svg=svg,
        )

    def commit_study_schema(
        self,
        project_id: str,
        request: MedicalWritingStudySchemaCommitRequest,
    ) -> MedicalWritingStudySchemaSnapshot:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return self.study_schema_snapshot(project_id)
        # Commit re-validates plan alignment via impact preview (same revision).
        preview = self.study_schema_impact_preview(project_id, request)
        if preview.requires_confirmation and request.impact_preview_id != preview.preview_id:
            raise MedicalWritingAuthoringJourneyConflictError(
                "study-schema change requires the current impact preview to be confirmed"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return self.study_schema_snapshot(project_id)
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != request.expected_journey_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "stale authoring journey revision: "
                    f"expected {request.expected_journey_revision}, current {current.revision}"
                )
            definition = current.study_definition
            if definition is None:
                connection.rollback()
                raise ValueError("the project has no versioned StudyDefinition")
            facts_sha256 = _study_definition_facts_sha256(
                definition.framing, definition.picos
            )
            if request.study_schema.source_facts_sha256 != facts_sha256:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "StudyDefinition facts changed before the study schema was committed"
                )
            now = datetime.now(timezone.utc)
            existing_schema = definition.study_schema
            schema_id = "mwschema_" + hashlib.sha256(
                project_id.encode("utf-8")
            ).hexdigest()[:20]
            schema = request.study_schema.model_copy(
                update={
                    "schema_id": schema_id,
                    "revision": existing_schema.revision + 1 if existing_schema else 1,
                    "source_facts_sha256": facts_sha256,
                    "status": (
                        "draft"
                        if any(issue.severity == "blocker" for issue in preview.issues)
                        else "confirmed"
                    ),
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            schema = schema.model_copy(
                update={"state_sha256": study_schema_state_sha256(schema)}, deep=True
            )
            updated_definition = _replace_study_definition_schema(
                definition, schema, actor=request.actor, now=now
            )
            existing_overrides = []
            existing_layout_revision = -1
            if current.study_schema_presentation is not None:
                node_ids = {node.node_id for node in schema.nodes}
                existing_overrides = [
                    item
                    for item in current.study_schema_presentation.node_overrides
                    if item.node_id in node_ids
                ]
                existing_layout_revision = current.study_schema_presentation.layout_revision
            presentation = MedicalWritingStudySchemaPresentation(
                schema_id=schema.schema_id,
                schema_revision=schema.revision,
                source_schema_sha256=schema.state_sha256,
                layout_revision=max(0, existing_layout_revision + 1),
                node_overrides=existing_overrides,
                updated_at=now,
                updated_by=request.actor,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "study_definition": updated_definition,
                    "study_schema_presentation": presentation,
                    "invalidated_dependents": sorted(
                        set(current.invalidated_dependents)
                        | set(preview.affected_dependents)
                    ),
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_study_schema_committed",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "schema_id": schema.schema_id,
                    "schema_revision": schema.revision,
                    "schema_state_sha256": schema.state_sha256,
                    "status": schema.status,
                    "reason": request.reason,
                    "changed_fields": preview.changed_fields,
                    "affected_dependents": preview.affected_dependents,
                    "impact_preview_id": preview.preview_id,
                },
            )
            connection.commit()
        return self.study_schema_snapshot(project_id)

    def update_study_schema_layout(
        self,
        project_id: str,
        request: MedicalWritingStudySchemaLayoutUpdateRequest,
    ) -> MedicalWritingStudySchemaSnapshot:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return self.study_schema_snapshot(project_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return self.study_schema_snapshot(project_id)
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != request.expected_journey_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "stale authoring journey revision: "
                    f"expected {request.expected_journey_revision}, current {current.revision}"
                )
            schema = current.study_definition.study_schema if current.study_definition else None
            presentation = current.study_schema_presentation
            if schema is None or presentation is None:
                connection.rollback()
                raise ValueError("study schema must be committed before layout can be updated")
            if schema.revision != request.expected_schema_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "study-schema semantic revision changed before layout save"
                )
            if presentation.layout_revision != request.expected_layout_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "study-schema layout revision changed before layout save"
                )
            node_ids = {node.node_id for node in schema.nodes}
            unknown = sorted(
                item.node_id for item in request.node_overrides if item.node_id not in node_ids
            )
            if unknown:
                connection.rollback()
                raise ValueError(
                    "study-schema layout references unknown node(s): " + ", ".join(unknown)
                )
            now = datetime.now(timezone.utc)
            updated_presentation = presentation.model_copy(
                update={
                    "layout_revision": presentation.layout_revision + 1,
                    "node_overrides": sorted(
                        request.node_overrides, key=lambda item: item.node_id
                    ),
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "study_schema_presentation": updated_presentation,
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_study_schema_layout_updated",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "schema_id": schema.schema_id,
                    "schema_revision": schema.revision,
                    "layout_revision": updated_presentation.layout_revision,
                    "node_override_count": len(updated_presentation.node_overrides),
                    "clinical_topology_unchanged": True,
                },
            )
            connection.commit()
        return self.study_schema_snapshot(project_id)

    def project_discovery_basket(
        self,
        project_id: str,
        *,
        confirmation_id: str,
        confirmation_hash: str,
        snapshot_id: str,
        retained_nct_ids: list[str],
        excluded_nct_ids: list[str],
        run_id: str,
        actor: str,
        reason: str,
        expected_journey_revision: int,
        idempotency_key: str,
    ) -> MedicalWritingAuthoringJourney:
        """Project a confirmed discovery basket as a derived journey reference.

        This writes ``discovery_basket_projection`` on the journey. It does
        NOT require PICOS completion and does NOT finalize corpus triage.
        The authoritative confirmation remains in writing_reference.sqlite3.
        Idempotent: replays return the same journey state.
        """
        request_material = {
            "confirmation_id": confirmation_id,
            "confirmation_hash": confirmation_hash,
            "snapshot_id": snapshot_id,
            "retained_nct_ids": sorted(retained_nct_ids),
            "excluded_nct_ids": sorted(excluded_nct_ids),
            "run_id": run_id,
            "reason": reason,
        }
        request_sha256 = _payload_sha256(request_material)
        replay = self._replay_from_store(project_id, idempotency_key, request_sha256)
        if replay is not None:
            return replay

        state = self.get(project_id)
        if state.revision != expected_journey_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {expected_journey_revision}, current {state.revision}"
            )
        if state.search_plan is None or state.search_plan.latest_snapshot_id != snapshot_id:
            raise ValueError("discovery basket must use the snapshot bound to the journey")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != expected_journey_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {expected_journey_revision}, current {current.revision}"
                )
            now = datetime.now(timezone.utc)
            projection = DiscoveryBasketProjection(
                confirmation_id=confirmation_id,
                confirmation_hash=confirmation_hash,
                snapshot_id=snapshot_id,
                retained_nct_ids=sorted(retained_nct_ids),
                excluded_nct_ids=sorted(excluded_nct_ids),
                run_id=run_id,
                actor=actor,
                reason=reason,
                projected_at=now,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "discovery_basket_projection": projection,
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_discovery_basket_projected",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "confirmation_id": confirmation_id,
                    "snapshot_id": snapshot_id,
                    "retained_nct_ids": sorted(retained_nct_ids),
                },
            )
            connection.commit()
        return updated

    def finalize_corpus_triage(
        self,
        project_id: str,
        request: MedicalWritingCorpusTriageFinalizeRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return replay
        state = self.get(project_id)
        if state.revision != request.expected_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {request.expected_revision}, current {state.revision}"
            )
        if not state.picos_complete or state.search_plan is None:
            raise ValueError("PICOS and competitor search must be complete before triage finalization")
        if state.search_plan.latest_snapshot_id != request.snapshot_id:
            raise ValueError("triage must use the immutable snapshot bound to the authoring journey")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current.revision}"
                )
            now = datetime.now(timezone.utc)
            triage = MedicalWritingCorpusTriage(
                status="finalized",
                snapshot_id=request.snapshot_id,
                retained_candidate_ids=request.retained_candidate_ids,
                reason=request.reason,
                actor=request.actor,
                finalized_at=now,
            )
            search_plan = current.search_plan.model_copy(
                update={"status": "triaged"}, deep=True
            )
            gate = current.corpus_gate.model_copy(
                update={
                    "readiness_status": "not_ready",
                    "access_permitted": False,
                    "source_state_hash": "",
                    "evaluated_at": None,
                    "stale": True,
                    "override": current.corpus_gate.override.model_copy(
                        update={"active": False}, deep=True
                    ),
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "corpus_not_ready",
                    "current_stage": "corpus",
                    "search_plan": search_plan,
                    "corpus_triage": triage,
                    "corpus_gate": gate,
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_corpus_triage_finalized",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "snapshot_id": request.snapshot_id,
                    "retained_candidate_ids": request.retained_candidate_ids,
                },
            )
            connection.commit()
        return updated

    def record_picos_corpus_alignment(
        self,
        project_id: str,
        request: MedicalWritingPicosCorpusAlignmentRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return replay
        state = self.get(project_id)
        if state.revision != request.expected_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {request.expected_revision}, current {state.revision}"
            )
        if not state.picos_complete:
            raise ValueError("PICOS must be complete before corpus alignment review")
        current_picos_sha256 = self.picos_sha256(project_id)
        if request.source_picos_sha256 != current_picos_sha256:
            raise MedicalWritingAuthoringJourneyConflictError(
                "PICOS changed after the corpus alignment review was prepared"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current.revision}"
                )
            if _payload_sha256(current.picos.model_dump(mode="json")) != request.source_picos_sha256:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "PICOS changed after the corpus alignment review was prepared"
                )
            now = datetime.now(timezone.utc)
            alignment = MedicalWritingPicosCorpusAlignment(
                status=request.status,
                source_picos_sha256=request.source_picos_sha256,
                conflict_count=request.conflict_count,
                disposition_summary=request.disposition_summary,
                evidence_brief_ids=request.evidence_brief_ids,
                actor=request.actor,
                assessed_at=now,
            )
            gate = current.corpus_gate.model_copy(
                update={
                    "source_state_hash": "",
                    "evaluated_at": None,
                    "stale": True,
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "picos_corpus_alignment": alignment,
                    "corpus_gate": gate,
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_picos_corpus_alignment_recorded",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "status": request.status,
                    "conflict_count": request.conflict_count,
                    "evidence_brief_ids": request.evidence_brief_ids,
                },
            )
            connection.commit()
        return updated

    def apply_corpus_projection(
        self,
        project_id: str,
        *,
        bound_snapshot_id: str,
        source_state_hash: str,
        requirements: list[MedicalWritingCorpusRequirementStatus],
        actor: str = "system_corpus_readiness",
    ) -> MedicalWritingAuthoringJourney:
        state = self.get(project_id)
        if state.search_plan is None or state.search_plan.latest_snapshot_id != bound_snapshot_id:
            raise ValueError("corpus projection does not match the authoring journey snapshot")
        if len(requirements) != len(self._CORPUS_REQUIREMENTS):
            raise ValueError("corpus projection must evaluate every requirement")
        requirement_payload = [item.model_dump(mode="json") for item in requirements]
        if (
            not state.corpus_gate.stale
            and state.corpus_gate.source_state_hash == source_state_hash
            and [item.model_dump(mode="json") for item in state.corpus_gate.requirements]
            == requirement_payload
        ):
            return state
        missing = [item.label for item in requirements if not item.satisfied]
        covered = [item.label for item in requirements if item.satisfied]
        ready = not missing
        acknowledged = set(state.corpus_gate.override.acknowledged_missing_requirements)
        # The override stays valid once active (requirements-v2 R3): the
        # medical manager explicitly decided to proceed with acknowledged
        # gaps.  Requirement changes after the override don't invalidate it —
        # that would re-block the writing workflow the author already
        # unlocked.
        override_still_valid = bool(
            state.corpus_gate.override.active
        )
        access_permitted = ready or override_still_valid
        now = datetime.now(timezone.utc)
        gate = state.corpus_gate.model_copy(
            update={
                "readiness_status": "ready" if ready else "not_ready",
                "access_permitted": access_permitted,
                "missing_requirements": missing,
                "covered_requirements": covered,
                "requirements": requirements,
                "bound_snapshot_id": bound_snapshot_id,
                "source_state_hash": source_state_hash,
                "evaluated_at": now,
                "stale": False,
                "override": state.corpus_gate.override.model_copy(
                    update={"active": override_still_valid}, deep=True
                ),
            },
            deep=True,
        )
        request_sha256 = _payload_sha256(
            {
                "bound_snapshot_id": bound_snapshot_id,
                "source_state_hash": source_state_hash,
                "requirements": requirement_payload,
            }
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = _load_authoring_journey_payload(
                self._current_row(connection, project_id)["payload_json"]
            )
            if current.revision != state.revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "authoring journey changed during corpus readiness evaluation"
                )
            status = current.status
            if current.status != "document_created":
                if not current.framing_complete or not current.picos_complete:
                    # Corpus evidence can be projected while the two-stage
                    # study definition is still being completed.  Do not let
                    # a status refresh move a user out of the active framing
                    # or PICOS step; writing remains unavailable until the
                    # normal stage commits and PICOS alignment are complete.
                    status = current.status
                else:
                    status = "writing_allowed" if access_permitted else "corpus_not_ready"
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": status,
                    "current_stage": (
                        current.current_stage
                        if not current.framing_complete or not current.picos_complete
                        else ("writing" if access_permitted else "corpus")
                    ),
                    "corpus_gate": gate,
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_corpus_gate_recalculated",
                actor=actor,
                idempotency_key=f"corpus-projection-{source_state_hash}",
                request_sha256=request_sha256,
                detail={
                    "readiness_status": gate.readiness_status,
                    "missing_requirements": missing,
                    "source_state_hash": source_state_hash,
                },
            )
            connection.commit()
        return updated

    def override_corpus_gate(
        self,
        project_id: str,
        request: MedicalWritingCorpusGateOverrideRequest,
    ) -> MedicalWritingAuthoringJourney:
        request_sha256 = _payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        state = self.get(project_id)
        if request.expected_revision != state.revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale authoring journey revision: expected {request.expected_revision}, current {state.revision}"
            )
        if not state.framing_complete or not state.picos_complete:
            raise ValueError("study framing and PICOS must be complete before corpus override")
        missing = set(state.corpus_gate.missing_requirements)
        acknowledged = set(request.acknowledged_missing_requirements)
        if acknowledged != missing:
            raise ValueError("corpus gate override must acknowledge every current missing requirement")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            if current.revision != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale authoring journey revision: expected {request.expected_revision}, current {current.revision}"
                )
            if not current.framing_complete or not current.picos_complete:
                connection.rollback()
                raise ValueError(
                    "study framing and PICOS must be complete before corpus override"
                )
            current_missing = set(current.corpus_gate.missing_requirements)
            if set(request.acknowledged_missing_requirements) != current_missing:
                connection.rollback()
                raise ValueError(
                    "corpus gate override must acknowledge every current missing requirement"
                )
            now = datetime.now(timezone.utc)
            gate = current.corpus_gate.model_copy(
                update={
                    "access_permitted": True,
                    "override": MedicalWritingCorpusGateOverride(
                        active=True,
                        reason=request.reason,
                        actor=request.actor,
                        recorded_at=now,
                        acknowledged_missing_requirements=(
                            request.acknowledged_missing_requirements
                        ),
                    ),
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "writing_allowed",
                    "current_stage": "writing",
                    "corpus_gate": gate,
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_corpus_gate_overridden",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "readiness_status": gate.readiness_status,
                    "access_permitted": gate.access_permitted,
                    "acknowledged_missing_requirements": request.acknowledged_missing_requirements,
                },
            )
            connection.commit()
        return updated

    def build_competitor_search_request(
        self,
        project_id: str,
        request: MedicalWritingCompetitorSearchExecuteRequest,
    ) -> WritingReferenceSearchCreateRequest:
        state = self.get(project_id)
        effective_framing, _effective_picos = effective_authoring_values(state)
        if (
            not effective_framing.creation_minimum_complete()
            or state.search_plan is None
        ):
            raise ValueError(
                "creation minimum (investigational product, indication, study phase) "
                "and a valid search plan are required before competitor search"
            )
        if state.search_plan.plan_id != request.search_plan_id:
            raise MedicalWritingAuthoringJourneyConflictError(
                "competitor search plan changed; reload before searching"
            )
        registry_filter = state.search_plan.registry_filter
        if registry_filter is None or not registry_filter.condition_term:
            raise MedicalWritingAuthoringJourneyConflictError(
                "competitor search contract is incomplete; reload before searching"
            )
        from .medical_writing_condition_term_resolver import (
            resolve_clinicaltrials_condition_term,
        )

        resolved_condition, _alias = resolve_clinicaltrials_condition_term(
            indication=effective_framing.indication or "",
            clinicaltrials_condition_term=(
                effective_framing.clinicaltrials_condition_term
                or registry_filter.condition_term
                or ""
            ),
        )
        return WritingReferenceSearchCreateRequest(
            search=WritingReferenceSearchRequest(
                indication=resolved_condition,
                phases=registry_filter.phases,
                study_type=registry_filter.study_type,
                regions=registry_filter.regions,
                intervention_terms=registry_filter.intervention_terms,
                page_size=100,
            ),
            actor=request.actor,
            idempotency_key=f"{request.idempotency_key}:snapshot",
        )

    def attach_search_snapshot(
        self,
        project_id: str,
        snapshot: WritingReferenceSearchSnapshot,
        request: MedicalWritingCompetitorSearchExecuteRequest,
    ) -> MedicalWritingAuthoringJourney:
        if snapshot.project_id != project_id:
            raise ValueError("writing reference snapshot belongs to a different project")
        if snapshot.returned_count != len(snapshot.candidates):
            raise ValueError("writing reference snapshot candidate count is inconsistent")
        public_document_count = sum(
            sum(
                1
                for document in candidate.public_documents
                if document.document_type.lower() in {"protocol", "protocol_sap"}
            )
            for candidate in snapshot.candidates
        )
        request_sha256 = _payload_sha256(
            {
                **request.model_dump(mode="json", exclude={"actor", "idempotency_key"}),
                "snapshot_id": snapshot.snapshot_id,
                "returned_count": snapshot.returned_count,
                "public_document_count": public_document_count,
            }
        )
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        state = self.get(project_id)
        if state.search_plan is None:
            raise ValueError(
                "a valid competitor search plan is required before attaching a search snapshot"
            )
        if state.search_plan.plan_id != request.search_plan_id:
            raise MedicalWritingAuthoringJourneyConflictError(
                "search snapshot does not match the current competitor search plan"
            )
        if state.search_plan.latest_snapshot_id == snapshot.snapshot_id:
            return state
        if state.search_plan.latest_snapshot_id:
            # Allow replacing an empty / no-results snapshot so corrected
            # English condition terms can re-run discovery without forcing a
            # full journey rebuild. Non-empty prior results stay immutable.
            prior_empty = int(state.search_plan.returned_count or 0) == 0
            if not prior_empty:
                raise MedicalWritingAuthoringJourneyConflictError(
                    "the current competitor search plan already has an immutable search snapshot"
                )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            if current.search_plan is None or current.search_plan.plan_id != request.search_plan_id:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "search snapshot does not match the current competitor search plan"
                )
            if current.search_plan.latest_snapshot_id == snapshot.snapshot_id:
                connection.commit()
                return current
            if current.search_plan.latest_snapshot_id:
                prior_empty = int(current.search_plan.returned_count or 0) == 0
                if not prior_empty:
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "the current competitor search plan already has an immutable search snapshot"
                    )
            now = datetime.now(timezone.utc)
            search_plan = current.search_plan.model_copy(
                update={
                    "status": "triage_pending" if snapshot.returned_count else "no_results",
                    "latest_snapshot_id": snapshot.snapshot_id,
                    "returned_count": snapshot.returned_count,
                    "public_document_count": public_document_count,
                    "searched_at": snapshot.created_at,
                },
                deep=True,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "search_plan": search_plan,
                    "updated_at": now,
                    "updated_by": request.actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_search_snapshot_attached",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "search_plan_id": request.search_plan_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "returned_count": snapshot.returned_count,
                    "public_document_count": public_document_count,
                },
            )
            connection.commit()
        return updated

    def require_writing_access(self, project_id: str) -> None:
        if not self.has_project(project_id):
            return
        state = self.get(project_id)
        if (
            not state.framing_complete
            or not state.picos_complete
            or not state.corpus_gate.access_permitted
        ):
            raise ValueError(
                "project corpus is not ready; complete corpus preparation or record a reasoned medical override before creating a writing document"
            )

    def require_study_definition_binding(
        self,
        project_id: str,
        *,
        definition_id: str,
        revision: int | None,
        state_sha256: str,
    ) -> MedicalWritingStudyDefinition:
        state = self.get(project_id)
        definition = state.study_definition
        if definition is None:
            raise ValueError("the project has no versioned study definition")
        if (
            definition.definition_id != definition_id
            or definition.revision != revision
            or definition.state_sha256 != state_sha256
        ):
            raise MedicalWritingAuthoringJourneyConflictError(
                "the writing request is not bound to the current study definition"
            )
        if (
            definition.framing != state.framing
            or definition.picos != _canonical_study_definition_picos(state.picos)
            or not state.framing_complete
            or not state.picos_complete
        ):
            raise ValueError("the current study definition is not formally complete")
        return definition

    def reserve_document_creation(
        self,
        project_id: str,
        *,
        actor: str,
        request_idempotency_key: str,
    ) -> str:
        if not self.has_project(project_id):
            return ""
        request_idempotency_key = _required_text(
            request_idempotency_key, "request_idempotency_key"
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            if current.status == "document_created":
                connection.commit()
                return ""
            existing = current.document_creation_reservation
            if existing is not None:
                if existing.request_idempotency_key == request_idempotency_key:
                    connection.commit()
                    return existing.reservation_id
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "a writing-document creation reservation is already active"
                )
            if (
                not current.framing_complete
                or not current.picos_complete
                or not current.corpus_gate.access_permitted
            ):
                connection.rollback()
                raise ValueError(
                    "project corpus is not ready; complete corpus preparation or record a reasoned medical override before creating a writing document"
                )
            now = datetime.now(timezone.utc)
            source_gate_sha256 = self._document_creation_source_sha256(current)
            reservation_id = "mwdocres_" + _payload_sha256(
                {
                    "project_id": project_id,
                    "revision": current.revision,
                    "request_idempotency_key": request_idempotency_key,
                    "source_gate_sha256": source_gate_sha256,
                }
            )[:24]
            reservation = MedicalWritingDocumentCreationReservation(
                reservation_id=reservation_id,
                source_revision=current.revision,
                source_gate_sha256=source_gate_sha256,
                request_idempotency_key=request_idempotency_key,
                actor=actor,
                reserved_at=now,
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "document_creation_reserved",
                    "current_stage": "writing",
                    "document_creation_reservation": reservation,
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_document_creation_reserved",
                actor=actor,
                idempotency_key=f"document-reserved-{reservation_id}",
                request_sha256=_payload_sha256(reservation.model_dump(mode="json")),
                detail={
                    "reservation_id": reservation_id,
                    "source_revision": current.revision,
                    "source_gate_sha256": source_gate_sha256,
                },
            )
            connection.commit()
        return reservation_id

    def mark_document_created(
        self,
        project_id: str,
        actor: str = "medical_manager",
        reservation_id: str = "",
    ) -> None:
        if not self.has_project(project_id):
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            if current.status == "document_created":
                connection.commit()
                return
            reservation = current.document_creation_reservation
            if reservation is None or reservation.reservation_id != reservation_id:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "writing-document creation reservation is missing or stale"
                )
            if current.revision != reservation.source_revision + 1:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "authoring journey changed after document creation was reserved"
                )
            if self._document_creation_source_sha256(current) != reservation.source_gate_sha256:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "writing access facts changed after document creation was reserved"
                )
            now = datetime.now(timezone.utc)
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "document_created",
                    "current_stage": "writing",
                    "document_creation_reservation": None,
                    "invalidated_dependents": [],
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_document_created",
                actor=actor,
                idempotency_key=f"document-created-{reservation_id}",
                request_sha256=_payload_sha256(
                    {"document_created": True, "reservation_id": reservation_id}
                ),
                detail={"reservation_id": reservation_id},
            )
            connection.commit()

    def release_document_creation_reservation(
        self,
        project_id: str,
        *,
        reservation_id: str,
        actor: str,
    ) -> None:
        if not reservation_id or not self.has_project(project_id):
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            reservation = current.document_creation_reservation
            if reservation is None:
                connection.commit()
                return
            if reservation.reservation_id != reservation_id:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "cannot release another writing-document creation reservation"
                )
            now = datetime.now(timezone.utc)
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": (
                        "writing_allowed"
                        if current.corpus_gate.access_permitted
                        else "corpus_not_ready"
                    ),
                    "current_stage": (
                        "writing" if current.corpus_gate.access_permitted else "corpus"
                    ),
                    "document_creation_reservation": None,
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_document_creation_reservation_released",
                actor=actor,
                idempotency_key=f"document-reservation-released-{reservation_id}",
                request_sha256=_payload_sha256(
                    {"reservation_released": True, "reservation_id": reservation_id}
                ),
                detail={"reservation_id": reservation_id},
            )
            connection.commit()

    def acknowledge_document_synchronization(
        self,
        project_id: str,
        *,
        definition_id: str,
        definition_revision: int,
        definition_sha256: str,
        actor: str,
        idempotency_key: str,
    ) -> MedicalWritingAuthoringJourney:
        """Acknowledge that the writing document now reflects the current definition."""

        request_payload = {
            "definition_id": definition_id,
            "definition_revision": definition_revision,
            "definition_sha256": definition_sha256,
        }
        request_sha256 = _payload_sha256(request_payload)
        replay = self._replay_from_store(project_id, idempotency_key, request_sha256)
        if replay is not None:
            return replay
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            definition = current.study_definition
            if definition is None:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "cannot synchronize a writing document without StudyDefinition"
                )
            if (
                definition.definition_id != definition_id
                or definition.revision != definition_revision
                or definition.state_sha256 != definition_sha256
            ):
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "StudyDefinition changed during writing-document synchronization"
                )
            now = datetime.now(timezone.utc)
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "invalidated_dependents": [],
                    "updated_at": now,
                    "updated_by": actor,
                },
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_document_synchronized",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                detail={
                    **request_payload,
                    "cleared_invalidated_dependents": current.invalidated_dependents,
                },
            )
            connection.commit()
            return updated

    def generate_prefill(
        self,
        project_id: str,
        request: "AuthoringPrefillGenerateRequest",
        *,
        snapshot: "WritingReferenceSearchSnapshot | None" = None,
        adapter: "PrefillRankingAdapter | None" = None,
        ai_enricher: "Any | None" = None,
    ) -> MedicalWritingAuthoringJourney:
        """Generate (or regenerate) the authoring prefill package.

        When *ai_enricher* is provided, it is called **outside** the SQLite
        write transaction so the external model call does not hold a write
        lock.  The deterministic package is always generated first; the AI
        enricher may then merge candidates into it.  On any AI failure the
        deterministic package is preserved as a complete fallback.

        Exactly-once guarantee (worker_02 corrective round): before any
        enrichment call a durable fail-closed reservation keyed by
        (project_id, expected_revision, operation) is acquired in the
        journey store.  A duplicate logical call with the same key waits
        for the winner and replays its outcome instead of dispatching a
        second model call.  The reservation records the logical call id
        and its single transport attempt, completes atomically with the
        generation event, and preserves an unknown-outcome state across
        timeout or restart without automatic redispatch (force=True starts
        a new logical call).
        """
        request_payload = {
            "expected_revision": request.expected_revision,
            "force": request.force,
        }
        request_sha256 = _payload_sha256(request_payload)
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return replay

        # ---- Phase 1: read-only preconditions (no transaction) ----
        current = self.get(project_id)
        if current.revision != request.expected_revision:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"stale journey revision: expected {request.expected_revision}, "
                f"actual {current.revision}"
            )
        effective_framing, effective_picos = effective_authoring_values(current)
        effective_state = current.model_copy(
            update={"framing": effective_framing, "picos": effective_picos},
            deep=True,
        )
        if not effective_framing.creation_minimum_complete():
            raise ValueError(
                "prefill generation requires creation minimum: "
                "investigational product, indication and study phase"
            )
        existing = current.prefill_package
        if (
            existing is not None
            and not request.force
            and not package_is_stale(
                existing,
                state=effective_state,
                snapshot=snapshot,
            )
        ):
            return current

        # ---- Phase 2: deterministic package + AI enrichment (no transaction) ----
        now = datetime.now(timezone.utc)
        deterministic_package = generate_prefill_package(
            state=effective_state,
            now=now,
            actor=request.actor,
            snapshot=snapshot,
            adapter=adapter,
        )
        # Attach the immutable project-fact catalog before any optional AI
        # enrichment.  This gives the deterministic creation-minimum title
        # the same live-verification/idempotency contract as an AI candidate;
        # it does not unlock heuristic design/PICOS fields.  In a bound
        # round-1 corpus journey, a missing read-only bridge is fail-closed
        # and leaves the deterministic package unchanged.
        if ai_enricher is not None:
            try:
                from .medical_writing_authoring_prefill_evidence import (
                    build_evidence_catalog,
                )
                from .medical_writing_authoring_prefill_evidence_binding import (
                    bind_deterministic_project_fact_candidates,
                )

                deterministic_catalog = build_evidence_catalog(
                    effective_state,
                    snapshot=snapshot,
                    corpus_analysis_reader=getattr(
                        ai_enricher, "_corpus_analysis_reader", None
                    ),
                    corpus_source_reader=getattr(
                        ai_enricher, "_corpus_source_reader", None
                    ),
                    journey_revision=current.revision + 1,
                )
                deterministic_package = bind_deterministic_project_fact_candidates(
                    package=deterministic_package,
                    catalog=deterministic_catalog,
                    product=effective_framing.investigational_product,
                    indication=effective_framing.indication,
                    phase=effective_framing.study_phase,
                )
            except Exception as exc:
                # A corpus-bound journey without its immutable bridge must
                # not be made writable by a partial catalog.  Preserve the
                # deterministic fallback and leave a precise audit note.
                from .medical_writing_authoring_prefill_corpus_bridge import (
                    CorpusPrefillBridgeError,
                )

                if isinstance(exc, CorpusPrefillBridgeError):
                    deterministic_package = deterministic_package.model_copy(
                        update={
                            "partial_source_failures": list(
                                deterministic_package.partial_source_failures
                            )
                            + [
                                "deterministic_project_fact_binding_skipped: "
                                f"{type(exc).__name__}: {exc}"
                            ]
                        },
                        deep=True,
                    )
                else:
                    raise
        # Hard gate: do not unlock design/PICOS packages until real research
        # corpus path is ready. Corpus-gate override alone is insufficient.
        from .medical_writing_research_pipeline import (
            research_ready_for_design_recommendations,
        )

        design_ready, design_block_reason = research_ready_for_design_recommendations(
            effective_state.model_copy(
                update={"research_pipeline": current.research_pipeline or {}},
                deep=True,
            )
        )
        if not design_ready:
            # Keep the non-adoptable deterministic scaffolds visible so the
            # user can understand and prepare the upcoming decisions while
            # research runs. The deterministic generator marks every design
            # and package scaffold pending_decision/manual_only; only
            # evidence-bound AI recommendations remain blocked here.
            failures = list(deterministic_package.partial_source_failures or [])
            failures.append(f"design_recommendations_blocked:{design_block_reason}")
            deterministic_package = deterministic_package.model_copy(
                update={
                    "partial_source_failures": failures,
                }
            )
        enriched_package = deterministic_package
        generation_reservation_call_id: str | None = None
        generation_reservation_timed_out = False
        generation_reservation_failed = False
        generation_reservation_dispatched = False
        if ai_enricher is not None and design_ready:
            # Durable fail-closed reservation (worker_02 corrective round):
            # acquired BEFORE any enrichment call, keyed by (project,
            # expected revision, operation).  A duplicate logical call with
            # the same key waits for the winner and replays its outcome, or
            # fails closed on an unknown-outcome state; it never dispatches
            # a second model call.
            acquisition = self._acquire_generation_reservation(
                project_id=project_id,
                expected_revision=current.revision,
                operation=_GENERATION_RESERVATION_OPERATION,
                force=request.force,
                enricher_timeout_seconds=float(
                    getattr(ai_enricher, "_timeout_seconds", 300.0)
                ),
            )
            if acquisition.replay is not None:
                return acquisition.replay
            generation_reservation_call_id = acquisition.logical_call_id
            try:
                # Bound the provider call outside the SQLite transaction. Use
                # one attempt only: Python threads cannot safely cancel an
                # in-flight HTTP request, so a timeout retry would duplicate
                # the same costly model call while the first request continues.
                import concurrent.futures

                def _run_enrich(timeout_s: float):
                    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    future = pool.submit(
                        ai_enricher.enrich_package,
                        package=deterministic_package,
                        state=effective_state,
                        snapshot=snapshot,
                        # Build the evidence catalog against the next
                        # persisted journey revision so the persisted catalog
                        # and the live catalog rebuilt at adoption time share
                        # one identity (package.journey_revision ==
                        # catalog.journey_revision == journey.revision).
                        journey_revision=current.revision + 1,
                    )
                    try:
                        return future.result(timeout=timeout_s)
                    except concurrent.futures.TimeoutError as exc:
                        if future.done():
                            raise
                        future.cancel()
                        raise TimeoutError(
                            f"authoring_prefill_ai: enrich_package timed out after {int(timeout_s)}s"
                        ) from exc
                    finally:
                        try:
                            pool.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            pool.shutdown(wait=False)

                provider_timeout = float(
                    getattr(ai_enricher, "_timeout_seconds", 300.0)
                )
                # Record the single physical transport attempt right before
                # dispatch: the prefill route is restricted to at most one
                # upstream POST (ai_gateway max_attempts=1), and a crash
                # around dispatch must be treated conservatively as one
                # attempted POST.
                self._mark_generation_reservation_dispatched(
                    project_id=project_id,
                    expected_revision=current.revision,
                    operation=_GENERATION_RESERVATION_OPERATION,
                    logical_call_id=generation_reservation_call_id,
                )
                generation_reservation_dispatched = True
                enriched_package = _run_enrich(max(30.0, provider_timeout + 15.0))
            except (TimeoutError, concurrent.futures.TimeoutError) as exc:
                # The model call may still be running server-side; its
                # outcome is unknown.  Keep the deterministic package as a
                # complete fallback and mark the reservation
                # unknown_outcome atomically with the fallback event; the
                # call is never redispatched automatically.
                generation_reservation_timed_out = True
                failures = list(deterministic_package.partial_source_failures)
                failures.append(
                    "authoring_prefill_ai: enrich_package timed out "
                    f"(logical call {generation_reservation_call_id}); "
                    "outcome unknown; no automatic redispatch"
                )
                enriched_package = deterministic_package.model_copy(
                    update={"partial_source_failures": failures},
                    deep=True,
                )
            except Exception as exc:
                # AI enricher failed (non-timeout terminal exception); keep
                # the deterministic package and record a
                # partial_source_failures entry.  Worker_03 corrective: the
                # event telemetry must record ai_outcome=failed — the call
                # returned an error, not a completed enrichment and not an
                # unknown timeout outcome.
                generation_reservation_failed = True
                failures = list(deterministic_package.partial_source_failures)
                failures.append(
                    f"authoring_prefill_ai: enrich_package failed ({type(exc).__name__})"
                )
                enriched_package = deterministic_package.model_copy(
                    update={"partial_source_failures": failures},
                    deep=True,
                )

        enriched_package = enriched_package.model_copy(
            update={"journey_revision": current.revision + 1},
            deep=True,
        )
        enriched_package = lock_confirmed_synopsis_values(
            package=enriched_package,
            state=effective_state,
        )
        enriched_package = preserve_current_user_confirmations(
            package=enriched_package,
            previous_package=existing,
            state=effective_state,
        )

        # ---- Phase 3: persist inside a short write transaction ----
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                replay = self._idempotent_replay(
                    connection, project_id, request.idempotency_key, request_sha256
                )
                if replay is not None:
                    connection.commit()
                    return replay
                current_row = self._current_row(connection, project_id)
                persisted = _load_authoring_journey_payload(
                    current_row["payload_json"]
                )
                if persisted.revision != current.revision:
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        f"stale journey revision: expected {current.revision}, "
                        f"actual {persisted.revision}"
                    )
                updated = persisted.model_copy(
                    update={
                        "revision": persisted.revision + 1,
                        "prefill_package": enriched_package,
                        "updated_at": now,
                        "updated_by": request.actor,
                    },
                    deep=True,
                )
                detail = {
                    "package_id": enriched_package.package_id,
                    "package_revision": enriched_package.package_revision,
                    "package_status": enriched_package.status,
                    "field_count": len(enriched_package.field_candidates),
                    "input_fingerprint": enriched_package.input_fingerprint,
                    "ai_run_id": enriched_package.ai_run_id,
                    "ai_provider": enriched_package.ai_provider,
                    "model_name": enriched_package.model_name,
                    "prompt_version": enriched_package.prompt_version,
                    "ai_input_sha256": enriched_package.ai_input_sha256,
                    "ai_output_sha256": enriched_package.ai_output_sha256,
                }
                if generation_reservation_call_id is not None:
                    # Telemetry: the logical call id and its single
                    # transport attempt are recorded on the same event that
                    # completes the reservation.  Worker_03 corrective:
                    # non-timeout enricher failures are "failed" — only a
                    # returned enrichment is "completed", and a timeout
                    # keeps the unknown-outcome semantics.
                    detail["ai_logical_call_id"] = generation_reservation_call_id
                    detail["ai_transport_attempt_count"] = 1
                    detail["ai_outcome"] = (
                        "failed"
                        if generation_reservation_failed
                        else (
                            "unknown_outcome"
                            if generation_reservation_timed_out
                            else "completed"
                        )
                    )
                event_id = self._persist_update(
                    connection,
                    updated,
                    expected_revision=persisted.revision,
                    event_type="authoring_journey_prefill_generated",
                    actor=request.actor,
                    idempotency_key=request.idempotency_key,
                    request_sha256=request_sha256,
                    detail=detail,
                )
                if generation_reservation_call_id is not None:
                    # Complete the reservation atomically with the
                    # generation event: both commit or neither.
                    self._complete_generation_reservation(
                        connection,
                        project_id=project_id,
                        expected_revision=current.revision,
                        operation=_GENERATION_RESERVATION_OPERATION,
                        logical_call_id=generation_reservation_call_id,
                        status=(
                            "unknown_outcome"
                            if generation_reservation_timed_out
                            else "completed"
                        ),
                        event_id=event_id,
                    )
                connection.commit()
                return updated
        except Exception as exc:
            if generation_reservation_call_id is not None:
                # The generation event was not persisted: release the
                # reservation so the key stays recoverable.  Once the
                # reservation was marked dispatched the upstream model may
                # have completed and only the local result was lost, so
                # every non-committed terminal path is unknown_outcome
                # (fail closed, force-only recovery) regardless of whether
                # the provider returned, raised, or the local transaction
                # failed.  Only a provably pre-dispatch failure may be
                # retryable as failed.
                self._release_generation_reservation(
                    project_id=project_id,
                    expected_revision=current.revision,
                    operation=_GENERATION_RESERVATION_OPERATION,
                    logical_call_id=generation_reservation_call_id,
                    status=(
                        "failed"
                        if not generation_reservation_dispatched
                        else "unknown_outcome"
                    ),
                    note=(
                        f"generation event not persisted ({type(exc).__name__})"
                        if not generation_reservation_dispatched
                        else (
                            f"generation event not persisted ({type(exc).__name__}); "
                            "transport attempt was dispatched, outcome unknown"
                        )
                    ),
                )
            raise

    def adopt_prefill_candidate(
        self,
        project_id: str,
        request: "AuthoringPrefillAdoptRequest",
        *,
        evidence_verifier: "EvidencePathVerifier | None" = None,
    ) -> MedicalWritingAuthoringJourney:
        request_payload = {
            "expected_revision": request.expected_revision,
            "expected_package_revision": request.expected_package_revision,
            "field_path": request.field_path,
            "candidate_id": request.candidate_id,
            "edited_value": request.edited_value,
        }
        request_sha256 = _payload_sha256(request_payload)
        replay = self._replay_from_store(project_id, request.idempotency_key, request_sha256)
        if replay is not None:
            return replay
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                return replay
            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )
            if current.revision != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale journey revision: expected {request.expected_revision}, "
                    f"actual {current.revision}"
                )
            package = current.prefill_package
            if package is None:
                connection.rollback()
                raise ValueError("no prefill package exists for this project")
            if package.package_revision != request.expected_package_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale package revision: expected {request.expected_package_revision}, "
                    f"actual {package.package_revision}"
                )
            if package.status == "stale":
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "prefill package is stale; regenerate before adopting"
                )
            field_path = request.field_path
            if field_path not in SUPPORTED_ADOPT_PATHS:
                connection.rollback()
                raise ValueError(f"unsupported prefill adoption path: {field_path}")
            field_group = package.field_candidates.get(field_path)
            adopted_value = request.edited_value
            adopted_candidate_id = request.candidate_id
            target = None
            if field_group is not None and request.candidate_id:
                target = next(
                    (c for c in field_group.candidates if c.candidate_id == request.candidate_id),
                    None,
                )
                if target is None:
                    connection.rollback()
                    raise ValueError(
                        f"candidate {request.candidate_id} not found in field {field_path}"
                    )
                if target.state == "user_confirmed":
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate already confirmed; newer user-confirmed values "
                        "must not be silently overwritten"
                    )
                # P2 gate (corrective round 2): the single-candidate path
                # fails closed for every pending / manual-only candidate and
                # every server-derived pending candidate, regardless of
                # whether it carries evidence bindings.  No generic override
                # flag exists on this endpoint; user overrides remain on the
                # composite override/skip path with its audit.  Candidates
                # that survive the role/mode gates and carry evidence are
                # then live-verified against the current evidence catalog
                # (same semantics as the composite path): tampered, stale, or
                # unsupported bindings fail closed.
                if target.recommendation_role == "pending_decision":
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate is pending_decision; single-candidate "
                        "adoption is blocked (user overrides remain on the "
                        "composite adoption path)"
                    )
                if target.adoption_mode == "manual_only":
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate is manual_only; single-candidate "
                        "adoption is blocked (user overrides remain on the "
                        "composite adoption path)"
                    )
                # Server-derived pending: bindings to insufficient-support
                # corpus observations force pending_decision; a persisted
                # candidate promoted to recommended/alternative must never be
                # adoptable (same rule as generation-side validation).
                from .medical_writing_authoring_prefill_evidence_binding import (
                    server_candidate_requires_pending_decision,
                )

                entry_lookup = {}
                if package.evidence_catalog is not None:
                    entry_lookup = {
                        e.catalog_entry_id: e
                        for e in package.evidence_catalog.entries
                    }
                if server_candidate_requires_pending_decision(
                    target, entry_lookup
                ):
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate is bound to insufficient-support corpus "
                        "evidence and requires pending_decision; "
                        "single-candidate adoption is blocked"
                    )
                # Defense in depth (corrective round 2, worker_03): a
                # candidate whose evidence status is insufficient or whose
                # visible evidence gaps mark a substantive claim absent from
                # every bound quote is rejected BEFORE any verifier result —
                # it can never be adopted as an unqualified alternative.
                from .medical_writing_authoring_prefill_ai import (
                    _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX,
                )

                if str(target.evidence_status or "").strip() == "insufficient":
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate evidence_status is insufficient; "
                        "single-candidate adoption is blocked"
                    )
                if any(
                    str(gap).startswith(_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX)
                    for gap in (target.evidence_gaps or [])
                ):
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "candidate carries an unsupported-substantive "
                        "evidence gap; single-candidate adoption is blocked"
                    )
                # Evidence-bound non-pending candidates require live server
                # verification.
                if target.claim_bindings or target.evidence_catalog_id:
                    if evidence_verifier is None:
                        connection.rollback()
                        raise MedicalWritingAuthoringJourneyConflictError(
                            "evidence-bound candidate requires server evidence "
                            "verification"
                        )
                    verified = bool(
                        evidence_verifier.verify_candidate_path(
                            project_id=project_id,
                            package=package,
                            candidate=target,
                            target_path=field_path,
                            proposed_value=(
                                request.edited_value
                                if request.edited_value is not None
                                else target.structured_value
                            ),
                        )
                    )
                    if not verified:
                        connection.rollback()
                        raise MedicalWritingAuthoringJourneyConflictError(
                            "server evidence verification rejected candidate "
                            f"{target.candidate_id}: binding is tampered, stale, "
                            "or unsupported by the current evidence catalog"
                        )
                adopted_value = (
                    request.edited_value
                    if request.edited_value is not None
                    else target.structured_value
                )
                adopted_candidate_id = (
                    f"edited_{field_path}_{request.idempotency_key[:12]}"
                    if request.edited_value is not None
                    and values_materially_distinct(
                        request.edited_value,
                        target.structured_value,
                    )
                    else target.candidate_id
                )
            elif request.edited_value is not None:
                adopted_candidate_id = f"edited_{field_path}_{request.idempotency_key[:12]}"
            else:
                connection.rollback()
                raise ValueError("prefill adopt requires a candidate_id or edited_value")
            now = datetime.now(timezone.utc)
            effective_framing, effective_picos = effective_authoring_values(current)
            framing_payload = effective_framing.model_dump(mode="json")
            picos_payload = effective_picos.model_dump(mode="json")
            framing_updates, picos_updates, changed_paths = map_design_adoption_to_study_updates(
                field_path,
                adopted_value,
                framing_payload=framing_payload,
                picos_payload=picos_payload,
            )
            new_framing = type(effective_framing).model_validate(
                {**framing_payload, **framing_updates}
            )
            new_picos = type(effective_picos).model_validate(
                {**picos_payload, **picos_updates}
            )
            updated_candidates = dict(package.field_candidates)
            user_edited_candidate = None
            if adopted_candidate_id.startswith("edited_"):
                if isinstance(adopted_value, str):
                    edited_preview = adopted_value.strip()
                else:
                    edited_preview = json.dumps(
                        adopted_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                user_edited_candidate = AuthoringPrefillCandidate(
                    candidate_id=adopted_candidate_id,
                    field_path=field_path,
                    structured_value=adopted_value,
                    preview=edited_preview[:5_000],
                    evidence_refs=[
                        AuthoringPrefillEvidenceRef(
                            source_kind="manual",
                            source_id=f"user_edit:{request.actor}",
                            locator=field_path,
                            source_text=edited_preview[:5_000],
                        )
                    ],
                    rationale="医学经理在候选基础上精调并明确采用。",
                    limitations=(
                        ["该修订的新增内容由用户确认，不自动视为原候选证据所支持。"]
                        if target is not None and target.evidence_refs
                        else []
                    ),
                    confidence="none",
                    state="user_confirmed",
                )
            if field_path in updated_candidates:
                group = updated_candidates[field_path]
                new_items = []
                for c in group.candidates:
                    if c.candidate_id == adopted_candidate_id:
                        new_items.append(c.model_copy(update={"state": "user_confirmed"}, deep=True))
                    elif c.state == "user_confirmed":
                        new_items.append(c.model_copy(update={"state": "superseded"}, deep=True))
                    else:
                        new_items.append(c)
                if user_edited_candidate is not None:
                    new_items = [user_edited_candidate, *new_items][:5]
                updated_candidates[field_path] = group.model_copy(
                    update={
                        "recommended_candidate_id": adopted_candidate_id,
                        "candidates": new_items,
                    },
                    deep=True,
                )
            elif user_edited_candidate is not None:
                updated_candidates[field_path] = AuthoringPrefillFieldCandidates(
                    field_path=field_path,
                    recommended_candidate_id=adopted_candidate_id,
                    candidates=[user_edited_candidate],
                )
            new_package = package.model_copy(
                update={
                    "package_revision": package.package_revision + 1,
                    "field_candidates": updated_candidates,
                    "updated_at": now,
                },
                deep=True,
            )
            impacted = set()
            for changed_path in changed_paths:
                for dependent in self._IMPACT_MAP.get(changed_path, []):
                    impacted.add(dependent)
            new_study_definition = current.study_definition
            if current.study_definition is not None:
                confirmed_stages = set()
                if current.framing_complete:
                    confirmed_stages.add("framing")
                if current.picos_complete:
                    confirmed_stages.add("picos")
                new_study_definition = _build_study_definition(
                    project_id=current.project_id,
                    revision=current.study_definition.revision + 1,
                    origin=current.entry_mode,
                    framing=new_framing,
                    picos=new_picos,
                    synopsis_import=current.synopsis_import,
                    confirmed_stages=confirmed_stages,
                    actor=request.actor,
                    now=now,
                    created_at=current.study_definition.created_at,
                    current_study_schema=current.study_definition.study_schema,
                )
                new_study_definition = _merge_prefill_adoption_field_states(
                    previous=current.study_definition,
                    rebuilt=new_study_definition,
                    changed_paths=changed_paths,
                    actor=request.actor,
                    now=now,
                )
            state_updates: dict[str, Any] = {
                "revision": current.revision + 1,
                "study_definition": new_study_definition,
                "prefill_package": new_package,
                "invalidated_dependents": sorted(
                    set(current.invalidated_dependents) | impacted
                ),
                "updated_at": now,
                "updated_by": request.actor,
            }
            if current.framing_draft is not None:
                state_updates["framing_draft"] = current.framing_draft.model_copy(
                    update={
                        "framing": new_framing,
                        "missing_required_fields": new_framing.missing_required_fields(),
                        "saved_from_revision": current.revision,
                        "saved_at": now,
                        "saved_by": request.actor,
                    },
                    deep=True,
                )
            else:
                state_updates["framing"] = new_framing
            if current.picos_draft is not None:
                state_updates["picos_draft"] = current.picos_draft.model_copy(
                    update={
                        "picos": new_picos,
                        "missing_required_fields": new_picos.missing_required_fields(),
                        "saved_from_revision": current.revision,
                        "saved_at": now,
                        "saved_by": request.actor,
                    },
                    deep=True,
                )
            else:
                state_updates["picos"] = new_picos
            updated = current.model_copy(update=state_updates, deep=True)
            # F4: When adopting framing.clinicaltrials_condition_term (or any
            # other search-contract input), rebuild the versioned search plan
            # atomically so the next competitor search uses the new condition
            # term.  This replaces the old plan_id/revision rather than leaving
            # the stale Chinese-condition plan active.  If the current search
            # plan has a bound snapshot, clearing latest_snapshot_id forces
            # re-search before the next snapshot can be attached.
            if "competitor_search_plan" in impacted and updated.search_plan is not None:
                rebuilt_plan = self._search_plan(
                    project_id, new_framing, updated.revision, now
                )
                # Fail closed: if the rebuilt plan would be identical to the
                # old one (e.g. condition_term did not actually change the
                # filter), keep the old plan to avoid a no-op revision bump.
                if rebuilt_plan.plan_id != updated.search_plan.plan_id:
                    updated = updated.model_copy(
                        update={"search_plan": rebuilt_plan},
                        deep=True,
                    )
            new_package = new_package.model_copy(
                update={
                    "journey_revision": updated.revision,
                    "input_fingerprint": journey_input_fingerprint(updated),
                    "search_fingerprint": search_fingerprint(updated, None),
                    "corpus_fingerprint": updated.corpus_gate.source_state_hash or "",
                    "source_fact_fingerprint": (
                        new_study_definition.state_sha256
                        if new_study_definition is not None
                        else journey_input_fingerprint(updated)
                    ),
                },
                deep=True,
            )
            updated = updated.model_copy(
                update={"prefill_package": new_package},
                deep=True,
            )
            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_prefill_adopted",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "field_path": field_path,
                    "candidate_id": adopted_candidate_id,
                    "changed_paths": changed_paths,
                    "invalidated_dependents": sorted(impacted),
                    "package_revision": new_package.package_revision,
                },
            )
            connection.commit()
            return updated

    _COMPOSITE_OPERATION_DISCRIMINATOR = "authoring_prefill_composite_adopt_v1"

    _PACKAGE_STATUS_ALLOW = frozenset({"ready", "partial"})

    def adopt_prefill_composite(
        self,
        project_id: str,
        request: "AuthoringPrefillCompositeAdoptRequest",
        *,
        evidence_verifier=None,
    ) -> "AuthoringPrefillCompositeAdoptResult":
        """Atomically adopt a module/design_package candidate in a single
        BEGIN IMMEDIATE transaction. Returns a per-path receipt.

        evidence_verifier is an optional EvidencePathVerifier for W2b
        server-side binding validation. When None, exact_fact paths without
        bindings fail closed.
        """

        # Build the request hash with operation discriminator.
        request_payload = {
            "operation": self._COMPOSITE_OPERATION_DISCRIMINATOR,
            "expected_revision": request.expected_revision,
            "expected_package_revision": request.expected_package_revision,
            "package_field_path": request.package_field_path,
            "candidate_id": request.candidate_id,
            "path_overrides": _canonical_overrides(request.path_overrides),
            "skipped_paths": sorted(request.skipped_paths),
            "actor": request.actor,
        }
        request_sha256 = _payload_sha256(request_payload)

        # Pre-transaction idempotent replay check.
        replay = self._replay_from_store(
            project_id, request.idempotency_key, request_sha256
        )
        if replay is not None:
            receipt = self._load_composite_receipt_pre_transaction(
                project_id, request.idempotency_key
            )
            if receipt is None:
                # Receipt is missing or corrupted — fail closed, never
                # fabricate a replay receipt.
                raise MedicalWritingAuthoringJourneyConflictError(
                    "idempotent replay found a prior commit but could not "
                    "load the original receipt; refusing to fabricate"
                )
            receipt = receipt.model_copy(update={"replayed": True})
            return AuthoringPrefillCompositeAdoptResult(
                journey=replay.model_dump(mode="json"),
                receipt=receipt,
            )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            # In-transaction idempotent replay.
            replay = self._idempotent_replay(
                connection, project_id, request.idempotency_key, request_sha256
            )
            if replay is not None:
                connection.commit()
                receipt = self._load_composite_receipt_from_event(
                    connection, project_id, request.idempotency_key
                )
                if receipt is None:
                    connection.rollback()
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "idempotent replay found a prior commit but could not "
                        "load the original receipt; refusing to fabricate"
                    )
                receipt = receipt.model_copy(update={"replayed": True})
                return AuthoringPrefillCompositeAdoptResult(
                    journey=replay.model_dump(mode="json"),
                    receipt=receipt,
                )

            current_row = self._current_row(connection, project_id)
            current = _load_authoring_journey_payload(
                current_row["payload_json"]
            )

            # Journey revision CAS.
            journey_revision_before = current.revision
            if current.revision != request.expected_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale journey revision: expected {request.expected_revision}, "
                    f"actual {current.revision}"
                )

            package = current.prefill_package
            if package is None:
                connection.rollback()
                raise KeyError("no prefill package exists for this project")

            package_revision_before = package.package_revision

            # Package revision CAS.
            if package.package_revision != request.expected_package_revision:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"stale package revision: expected {request.expected_package_revision}, "
                    f"actual {package.package_revision}"
                )

            # Package status gate: only ready or partial allowed.
            if package.status not in self._PACKAGE_STATUS_ALLOW:
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    f"prefill package status '{package.status}' does not allow adoption; "
                    f"only 'ready' or 'partial' are acceptable"
                )

            # Locate candidate from server-authoritative package.
            field_group = package.field_candidates.get(request.package_field_path)
            if field_group is None:
                connection.rollback()
                raise KeyError(
                    f"prefill field group not found: {request.package_field_path}"
                )
            candidate = next(
                (
                    c
                    for c in field_group.candidates
                    if c.candidate_id == request.candidate_id
                ),
                None,
            )
            if candidate is None:
                connection.rollback()
                raise KeyError(
                    f"candidate {request.candidate_id} not found in field {request.package_field_path}"
                )

            # Candidate state gate.
            if candidate.state == "user_confirmed":
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "candidate already fully confirmed"
                )
            if candidate.state == "superseded":
                connection.rollback()
                raise MedicalWritingAuthoringJourneyConflictError(
                    "candidate has been superseded"
                )

            # Scope gate.
            if candidate.candidate_scope not in ("module", "design_package"):
                connection.rollback()
                raise ValueError(
                    f"composite adopt requires module or design_package scope, "
                    f"got {candidate.candidate_scope}"
                )

            # Field path consistency.
            if candidate.field_path != request.package_field_path:
                connection.rollback()
                raise ValueError(
                    f"candidate field_path '{candidate.field_path}' does not match "
                    f"request package_field_path '{request.package_field_path}'"
                )

            # Run the pure planner.
            effective_framing, effective_picos = effective_authoring_values(current)
            framing_payload = effective_framing.model_dump(mode="json")
            picos_payload = effective_picos.model_dump(mode="json")

            plan = plan_composite_adoption(
                project_id=project_id,
                candidate=candidate,
                package=package,
                path_overrides=request.path_overrides,
                skipped_paths=request.skipped_paths,
                framing_payload=framing_payload,
                picos_payload=picos_payload,
                impact_map=self._IMPACT_MAP,
                evidence_verifier=evidence_verifier,
            )

            # Validate final framing/picos models.
            new_framing = type(effective_framing).model_validate(
                {**framing_payload, **plan.framing_updates}
            )
            new_picos = type(effective_picos).model_validate(
                {**picos_payload, **plan.picos_updates}
            )

            now = datetime.now(timezone.utc)

            # Build updated candidates: mark original confirmed if fully applied.
            updated_candidates = dict(package.field_candidates)
            new_items: list[AuthoringPrefillCandidate] = []
            user_edited_composite: AuthoringPrefillCandidate | None = None

            # Determine applied value map for user-edited composite.
            applied_paths = sorted(
                set(plan.applied_candidate_paths) | set(plan.applied_override_paths)
            )
            applied_values: dict[str, Any] = {}
            for tp in applied_paths:
                if tp in request.path_overrides:
                    applied_values[tp] = request.path_overrides[tp]
                else:
                    applied_values[tp] = candidate.structured_value[tp]

            # If overrides were used and candidate is fully applied, create
            # a user-edited composite candidate.
            has_overrides = bool(plan.applied_override_paths)

            for c in field_group.candidates:
                if c.candidate_id == candidate.candidate_id:
                    if plan.candidate_fully_applied and not has_overrides:
                        new_items.append(
                            c.model_copy(
                                update={"state": "user_confirmed"}, deep=True
                            )
                        )
                    elif plan.candidate_fully_applied and has_overrides:
                        # Original gets superseded; we create a new user-edited below.
                        new_items.append(
                            c.model_copy(
                                update={"state": "superseded"}, deep=True
                            )
                        )
                    else:
                        # Partial adoption: do NOT change this candidate's state.
                        new_items.append(c)
                elif c.state == "user_confirmed" and plan.candidate_fully_applied:
                    # Only supersede prior user_confirmed candidates when the
                    # new composite is FULLY applied. Partial adoption must
                    # not overturn existing confirmed state.
                    new_items.append(
                        c.model_copy(update={"state": "superseded"}, deep=True)
                    )
                else:
                    new_items.append(c)

            # Create user-edited composite when overrides present and fully applied.
            if plan.candidate_fully_applied and has_overrides:
                edited_id = (
                    f"edited_composite_{request.package_field_path}_"
                    f"{request.idempotency_key[:12]}"
                )
                edited_preview = json.dumps(
                    applied_values,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )[:5000]
                user_edited_composite = AuthoringPrefillCandidate(
                    candidate_id=edited_id,
                    field_path=request.package_field_path,
                    structured_value=applied_values,
                    preview=edited_preview,
                    evidence_refs=(
                        # Build deduplicated evidence refs from non-override
                        # path bindings, one ref per unique catalog entry.
                        _build_edited_evidence_refs(
                            candidate=candidate,
                            applied_candidate_paths=plan.applied_candidate_paths,
                        )
                        + [
                            # Single manual ref for override paths only.
                            AuthoringPrefillEvidenceRef(
                                source_kind="manual",
                                source_id=f"user_override:{request.actor}",
                                locator=request.package_field_path,
                                source_text=edited_preview[:5000],
                            ),
                        ]
                    )[:20],
                    rationale="医学经理在组合候选基础上逐路径确认并采用。",
                    confidence="none",
                    state="user_confirmed",
                    candidate_scope=candidate.candidate_scope,
                    target_paths=sorted(applied_values.keys()),
                    recommendation_role="recommended",
                    evidence_catalog_id=candidate.evidence_catalog_id,
                    evidence_catalog_sha256=candidate.evidence_catalog_sha256,
                    claim_bindings=[
                        b for b in candidate.claim_bindings
                        if b.target_path in plan.applied_candidate_paths
                    ],
                    evidence_status=(
                        candidate.evidence_status
                        if any(b.target_path in plan.applied_candidate_paths for b in candidate.claim_bindings)
                        else "insufficient"
                    ),
                )
                new_items = [user_edited_composite, *new_items][:5]

            # If partially applied, do NOT mark candidate as user_confirmed.
            # The original candidate keeps its state or stays ai_proposed.
            if not plan.candidate_fully_applied:
                recommended_id = field_group.recommended_candidate_id
            elif has_overrides and user_edited_composite is not None:
                recommended_id = user_edited_composite.candidate_id
            else:
                recommended_id = candidate.candidate_id

            updated_candidates[request.package_field_path] = field_group.model_copy(
                update={
                    "recommended_candidate_id": recommended_id,
                    "candidates": new_items,
                },
                deep=True,
            )

            new_package = package.model_copy(
                update={
                    "package_revision": package.package_revision + 1,
                    "field_candidates": updated_candidates,
                    "updated_at": now,
                },
                deep=True,
            )

            # Build StudyDefinition with path-level confirmed_paths.
            # Prefill adopt should advance stage gates when required fields become filled
            # (lazy writer path: one-click packages → framing/picos complete without blank forms).
            framing_missing = new_framing.missing_required_fields()
            picos_missing = new_picos.missing_required_fields()
            new_framing_complete = not framing_missing
            new_picos_complete = new_framing_complete and not picos_missing

            has_fact_changes = bool(plan.all_changed_paths)
            new_study_definition = current.study_definition
            if current.study_definition is not None and has_fact_changes:
                confirmed_stages: set[str] = set()
                if new_framing_complete:
                    confirmed_stages.add("framing")
                if new_picos_complete:
                    confirmed_stages.add("picos")
                # Only applied + derived paths get confirmed; skipped stay as-is.
                confirmed_paths = set(plan.applied_candidate_paths) | set(
                    plan.applied_override_paths
                ) | set(plan.derived_paths)
                new_study_definition = _build_study_definition(
                    project_id=current.project_id,
                    revision=current.study_definition.revision + 1,
                    origin=current.entry_mode,
                    framing=new_framing,
                    picos=new_picos,
                    synopsis_import=current.synopsis_import,
                    confirmed_stages=confirmed_stages,
                    actor=request.actor,
                    now=now,
                    created_at=current.study_definition.created_at,
                    current_study_schema=current.study_definition.study_schema,
                    confirmed_paths=confirmed_paths,
                )
                new_study_definition = _merge_prefill_adoption_field_states(
                    previous=current.study_definition,
                    rebuilt=new_study_definition,
                    changed_paths=plan.all_changed_paths,
                    actor=request.actor,
                    now=now,
                )

            state_updates: dict[str, Any] = {
                "revision": current.revision + 1,
                "study_definition": new_study_definition,
                "prefill_package": new_package,
                "invalidated_dependents": sorted(
                    set(current.invalidated_dependents) | set(plan.impacted)
                ),
                "updated_at": now,
                "updated_by": request.actor,
            }
            if has_fact_changes:
                state_updates["framing_complete"] = new_framing_complete
                state_updates["picos_complete"] = new_picos_complete
            if has_fact_changes and new_picos_complete and not current.picos_complete:
                state_updates["current_stage"] = "corpus"
                state_updates["status"] = "corpus_not_ready"
            elif (
                has_fact_changes
                and new_framing_complete
                and not current.framing_complete
                and not new_picos_complete
            ):
                state_updates["current_stage"] = "picos"
                state_updates["status"] = "stage2_in_progress"

            # Formal / draft propagation.
            # When a stage becomes complete via lazy package adopt, promote the
            # working values into formal framing/picos and clear the stage draft
            # (same end-state as stages/{stage}/commit).
            if has_fact_changes and new_framing_complete:
                state_updates["framing"] = new_framing
                state_updates["framing_draft"] = None
            elif has_fact_changes and current.framing_draft is not None:
                state_updates["framing_draft"] = current.framing_draft.model_copy(
                    update={
                        "framing": new_framing,
                        "missing_required_fields": framing_missing,
                        "saved_from_revision": current.revision,
                        "saved_at": now,
                        "saved_by": request.actor,
                    },
                    deep=True,
                )
            elif has_fact_changes:
                state_updates["framing"] = new_framing

            if has_fact_changes and new_picos_complete:
                state_updates["picos"] = new_picos
                state_updates["picos_draft"] = None
            elif has_fact_changes and current.picos_draft is not None:
                state_updates["picos_draft"] = current.picos_draft.model_copy(
                    update={
                        "picos": new_picos,
                        "missing_required_fields": picos_missing,
                        "saved_from_revision": current.revision,
                        "saved_at": now,
                        "saved_by": request.actor,
                    },
                    deep=True,
                )
            elif has_fact_changes:
                state_updates["picos"] = new_picos

            updated = current.model_copy(update=state_updates, deep=True)

            # Ensure search plan exists once PICOS is complete (corpus stage entry).
            if has_fact_changes and new_picos_complete and updated.search_plan is None:
                updated = updated.model_copy(
                    update={
                        "search_plan": self._search_plan(
                            project_id, new_framing, updated.revision, now
                        )
                    },
                    deep=True,
                )

            # Search plan rebuild in same transaction.
            search_plan_rebuilt = False
            if (
                has_fact_changes
                and "competitor_search_plan" in plan.impacted
                and updated.search_plan is not None
            ):
                rebuilt_plan = self._search_plan(
                    project_id, new_framing, updated.revision, now
                )
                if rebuilt_plan.plan_id != updated.search_plan.plan_id:
                    updated = updated.model_copy(
                        update={"search_plan": rebuilt_plan},
                        deep=True,
                    )
                    search_plan_rebuilt = True

            # Package fingerprint update.
            package_marked_stale = False
            new_package = new_package.model_copy(
                update={
                    "journey_revision": updated.revision,
                    "input_fingerprint": journey_input_fingerprint(updated),
                    "search_fingerprint": search_fingerprint(updated, None),
                    "corpus_fingerprint": updated.corpus_gate.source_state_hash or "",
                    "source_fact_fingerprint": (
                        new_study_definition.state_sha256
                        if new_study_definition is not None
                        else journey_input_fingerprint(updated)
                    ),
                },
                deep=True,
            )
            # Mark package stale if search source changed — except when the
            # change came from adopting a package.* recommendation. Those
            # intentional framing/PICOS updates would otherwise lock the lazy
            # writer out of remaining one-click packages until regenerate.
            if search_plan_rebuilt and not request.package_field_path.startswith(
                "package."
            ):
                new_package = new_package.model_copy(
                    update={"status": "stale"},
                    deep=True,
                )
                package_marked_stale = True
            updated = updated.model_copy(
                update={"prefill_package": new_package},
                deep=True,
            )

            # Build receipt.
            operation_id = "mwcomposite_" + hashlib.sha256(
                f"{project_id}|{request.idempotency_key}".encode("utf-8")
            ).hexdigest()[:24]

            skipped_receipts = [
                AuthoringPrefillCompositeSkippedPath(path=path, reason=reason)
                for path, reason in plan.skipped_paths
            ]

            receipt = AuthoringPrefillCompositeAdoptReceipt(
                operation_id=operation_id,
                package_id=new_package.package_id,
                candidate_id=request.candidate_id,
                package_field_path=request.package_field_path,
                journey_revision_before=journey_revision_before,
                journey_revision_after=updated.revision,
                package_revision_before=package_revision_before,
                package_revision_after=new_package.package_revision,
                applied_paths=plan.applied_candidate_paths,
                overridden_paths=plan.applied_override_paths,
                derived_paths=plan.derived_paths,
                skipped_paths=skipped_receipts,
                invalidated_dependents=plan.impacted,
                search_plan_rebuilt=search_plan_rebuilt,
                package_marked_stale=package_marked_stale,
                replayed=False,
            )

            self._persist_update(
                connection,
                updated,
                expected_revision=current.revision,
                event_type="authoring_journey_prefill_composite_adopted",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                detail={
                    "operation_id": operation_id,
                    "package_field_path": request.package_field_path,
                    "candidate_id": request.candidate_id,
                    "applied_paths": plan.applied_candidate_paths,
                    "overridden_paths": plan.applied_override_paths,
                    "derived_paths": plan.derived_paths,
                    "skipped_paths": [
                        {"path": p, "reason": r} for p, r in plan.skipped_paths
                    ],
                    "invalidated_dependents": plan.impacted,
                    "search_plan_rebuilt": search_plan_rebuilt,
                    "package_marked_stale": package_marked_stale,
                    "candidate_fully_applied": plan.candidate_fully_applied,
                    "path_origins": dict(sorted(plan.path_origins.items())),
                    "receipt": receipt.model_dump(mode="json"),
                },
            )
            connection.commit()
            return AuthoringPrefillCompositeAdoptResult(
                journey=updated.model_dump(mode="json"),
                receipt=receipt,
            )
    def _load_composite_receipt_pre_transaction(
        self,
        project_id: str,
        idempotency_key: str,
    ) -> AuthoringPrefillCompositeAdoptReceipt | None:
        """Load a composite receipt from a prior event before entering the
        write transaction (separate connection)."""
        with self._connect() as connection:
            return self._load_composite_receipt_from_event(
                connection, project_id, idempotency_key
            )

    def _load_composite_receipt_from_event(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        idempotency_key: str,
    ) -> AuthoringPrefillCompositeAdoptReceipt | None:
        """Load a composite receipt from the persisted event payload."""
        row = connection.execute(
            """
            SELECT payload_json FROM medical_writing_authoring_journey_events
            WHERE project_id = ? AND idempotency_key = ?
            """,
            (project_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        try:
            detail = json.loads(row["payload_json"])
            receipt_data = detail.get("receipt")
            if receipt_data and isinstance(receipt_data, dict):
                return AuthoringPrefillCompositeAdoptReceipt.model_validate(
                    receipt_data
                )
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    @staticmethod
    def _document_creation_source_sha256(
        state: MedicalWritingAuthoringJourney,
    ) -> str:
        return _payload_sha256(
            {
                "framing": state.framing.model_dump(mode="json"),
                "picos": state.picos.model_dump(mode="json"),
                "framing_complete": state.framing_complete,
                "picos_complete": state.picos_complete,
                "corpus_gate": state.corpus_gate.model_dump(mode="json"),
            }
        )

    def _search_plan(self, project_id: str, framing, revision: int, now: datetime):
        registry_filter, triage_criteria, queries = (
            medical_writing_competitor_search_contract(framing)
        )
        return MedicalWritingCompetitorSearchPlan(
            plan_id="mwsearch_" + _payload_sha256(
                {
                    "project_id": project_id,
                    "revision": revision,
                    "registry_filter": registry_filter.model_dump(mode="json"),
                    "triage_criteria": [
                        item.model_dump(mode="json") for item in triage_criteria
                    ],
                }
            )[:24],
            plan_revision=revision,
            queries=queries,
            registry_filter=registry_filter,
            triage_criteria=triage_criteria,
            source_study_definition_revision=revision,
            generated_at=now,
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medical_writing_authoring_journeys (
                    project_id TEXT PRIMARY KEY,
                    journey_id TEXT NOT NULL UNIQUE,
                    revision INTEGER NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    create_request_sha256 TEXT NOT NULL,
                    create_idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medical_writing_authoring_journey_events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    journey_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_authoring_journey_events_project_revision
                    ON medical_writing_authoring_journey_events(project_id, revision, created_at);
                CREATE TABLE IF NOT EXISTS medical_writing_authoring_journey_generation_reservations (
                    project_id TEXT NOT NULL,
                    expected_revision INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    logical_call_id TEXT NOT NULL,
                    transport_attempt_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    event_id TEXT,
                    failure_note TEXT,
                    attempt_history TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, expected_revision, operation)
                );
                """
            )
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if version is None:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
            elif int(version) == SCHEMA_VERSION - 1:
                # v1 -> v2 (worker_02 corrective round 2): the generation
                # reservation gains the append-only attempt-history column
                # so a superseded logical call (id, attempt count, terminal
                # status, failure reason) stays auditable instead of being
                # overwritten by the next call.
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info("
                        "medical_writing_authoring_journey_generation_reservations)"
                    )
                }
                if "attempt_history" not in columns:
                    connection.execute(
                        "ALTER TABLE "
                        "medical_writing_authoring_journey_generation_reservations "
                        "ADD COLUMN attempt_history TEXT NOT NULL DEFAULT '[]'"
                    )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
            elif int(version) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported medical-writing authoring journey schema version: {version}"
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(
                    f"medical-writing authoring journey SQLite integrity check failed: {integrity}"
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
            SELECT project_id, journey_id, revision, state_sha256,
                   create_request_sha256, create_idempotency_key,
                   created_at, updated_at, payload_json
            FROM medical_writing_authoring_journeys WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"medical-writing authoring journey not found: {project_id}")
        return row

    def _idempotent_replay(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> MedicalWritingAuthoringJourney | None:
        row = connection.execute(
            """
            SELECT request_sha256 FROM medical_writing_authoring_journey_events
            WHERE project_id = ? AND idempotency_key = ?
            """,
            (project_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise MedicalWritingAuthoringJourneyConflictError(
                "authoring journey idempotency key was reused with different content"
            )
        current = self._current_row(connection, project_id)
        return _load_authoring_journey_payload(current["payload_json"])

    def _replay_from_store(
        self,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
    ) -> MedicalWritingAuthoringJourney | None:
        with self._connect() as connection:
            return self._idempotent_replay(
                connection, project_id, idempotency_key, request_sha256
            )

    # ------------------------------------------------------------------
    # Durable in-flight generation reservation (worker_02 corrective round)
    # ------------------------------------------------------------------

    @staticmethod
    def _generation_reservation_columns() -> tuple[str, ...]:
        return (
            "project_id",
            "expected_revision",
            "operation",
            "logical_call_id",
            "transport_attempt_count",
            "status",
            "event_id",
            "failure_note",
            "attempt_history",
            "created_at",
            "updated_at",
        )

    def _read_generation_reservation(
        self,
        project_id: str,
        expected_revision: int,
        operation: str,
    ) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM "
                "medical_writing_authoring_journey_generation_reservations "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ?",
                (project_id, expected_revision, operation),
            ).fetchone()

    def _read_generation_event(
        self,
        project_id: str,
        event_id: str,
    ) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT event_id, revision, event_type FROM "
                "medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND event_id = ?",
                (project_id, event_id),
            ).fetchone()

    def _replay_completed_reservation(
        self,
        project_id: str,
        expected_revision: int,
        operation: str,
        row: sqlite3.Row,
    ) -> _GenerationReservationAcquisition:
        """Replay the winner's outcome for a completed reservation key.

        Worker_03 corrective: the replay contract returns the CURRENT
        journey (the documented current-state replay), which may be a later
        revision than ``expected_revision`` when a subsequent force
        regeneration superseded the completed outcome.  The completion
        event is verified against the key (its revision must equal
        ``expected_revision + 1``) and its id/revision are returned as
        metadata so callers can explain the refresh.
        """
        completed_event_id = str(row["event_id"] or "").strip()
        if not completed_event_id:
            raise MedicalWritingAuthoringJourneyConflictError(
                "completed generation reservation lacks a completion event id"
            )
        event_row = self._read_generation_event(project_id, completed_event_id)
        if event_row is None:
            raise MedicalWritingAuthoringJourneyConflictError(
                f"generation reservation completion event {completed_event_id} "
                "is missing from the event store"
            )
        event_revision = int(event_row["revision"])
        if event_revision != expected_revision + 1:
            raise MedicalWritingAuthoringJourneyConflictError(
                "generation reservation completion event revision "
                f"{event_revision} does not match the reservation key "
                f"revision {expected_revision + 1}"
            )
        return _GenerationReservationAcquisition(
            replay=self.get(project_id),
            replay_event_id=completed_event_id,
            replay_event_revision=event_revision,
        )

    def _try_insert_generation_reservation(
        self,
        project_id: str,
        expected_revision: int,
        operation: str,
    ) -> str | None:
        """Insert a fresh in-flight reservation; None when a concurrent
        worker won the race (the caller re-reads and waits)."""
        logical_call_id = "mwprefillcall_" + uuid.uuid4().hex[:24]
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO "
                "medical_writing_authoring_journey_generation_reservations("
                "project_id, expected_revision, operation, logical_call_id, "
                "transport_attempt_count, status, event_id, failure_note, "
                "attempt_history, created_at, updated_at) VALUES (?, ?, ?, ?, 0, "
                "'in_flight', NULL, NULL, '[]', ?, ?)",
                (
                    project_id,
                    expected_revision,
                    operation,
                    logical_call_id,
                    now_iso,
                    now_iso,
                ),
            )
            connection.commit()
        return logical_call_id if cursor.rowcount == 1 else None

    def _supersede_generation_reservation(
        self,
        project_id: str,
        expected_revision: int,
        operation: str,
        *,
        previous_call_id: str,
        note: str,
    ) -> str | None:
        """Start a new logical call on a terminal (failed/unknown-outcome)
        reservation; None when a concurrent worker superseded it first.

        The superseded attempt is appended to ``attempt_history`` (JSON)
        instead of being erased, so the prior logical call id, transport
        attempt count, terminal status, and failure reason stay auditable.
        """
        logical_call_id = "mwprefillcall_" + uuid.uuid4().hex[:24]
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            # Read the terminal snapshot and re-key the reservation under the
            # same write lock.  Without an IMMEDIATE transaction, an old
            # owner can commit ``completed`` after this SELECT but before the
            # UPDATE, and the force caller would then overwrite the completed
            # row and dispatch a second transport for the same revision.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT logical_call_id, transport_attempt_count, status, "
                "event_id, failure_note, updated_at, attempt_history FROM "
                "medical_writing_authoring_journey_generation_reservations "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
                "AND logical_call_id = ?",
                (project_id, expected_revision, operation, previous_call_id),
            ).fetchone()
            if row is None:
                # A concurrent worker superseded (or completed) first.
                connection.rollback()
                return None
            previous_status = str(row["status"])
            if previous_status not in {"failed", "unknown_outcome"}:
                # The old owner completed (or another caller already
                # re-keyed the row) while the caller was deciding to force a
                # retry.  Never overwrite a terminal outcome.
                connection.rollback()
                return None
            history = json.loads(str(row["attempt_history"] or "[]"))
            history.append(
                {
                    "logical_call_id": str(row["logical_call_id"]),
                    "transport_attempt_count": int(
                        row["transport_attempt_count"] or 0
                    ),
                    "status": str(row["status"]),
                    "failure_note": row["failure_note"],
                    "updated_at": row["updated_at"],
                }
            )
            cursor = connection.execute(
                "UPDATE medical_writing_authoring_journey_generation_reservations "
                "SET logical_call_id = ?, transport_attempt_count = 0, "
                "status = 'in_flight', event_id = NULL, failure_note = ?, "
                "attempt_history = ?, updated_at = ? "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
                "AND logical_call_id = ? AND status = ? "
                "AND ((event_id IS NULL AND ? IS NULL) OR event_id = ?)",
                (
                    logical_call_id,
                    note,
                    json.dumps(history, ensure_ascii=False),
                    now_iso,
                    project_id,
                    expected_revision,
                    operation,
                    previous_call_id,
                    previous_status,
                    row["event_id"],
                    row["event_id"],
                ),
            )
            if cursor.rowcount != 1:
                # Defensive CAS: the status/event snapshot must still match
                # even though BEGIN IMMEDIATE normally serializes this
                # transaction with the completing owner.
                connection.rollback()
                return None
            connection.commit()
        return logical_call_id

    def _acquire_generation_reservation(
        self,
        *,
        project_id: str,
        expected_revision: int,
        operation: str,
        force: bool,
        enricher_timeout_seconds: float,
    ) -> _GenerationReservationAcquisition:
        """Acquire the durable fail-closed generation reservation.

        Runs BEFORE any enrichment call.  A second logical call with the
        same key (concurrent duplicate worker or retried request) waits for
        the winner and replays its outcome; it never dispatches another
        model call.  A timed-out or interrupted call is preserved as an
        unknown outcome and is never redispatched automatically: the key
        fails closed until an explicit ``force`` request starts a new
        logical call (recorded via a fresh logical call id).
        """
        wait_bound = (
            max(30.0, enricher_timeout_seconds + 15.0) + 5.0
            if self._generation_reservation_wait_seconds is None
            else self._generation_reservation_wait_seconds
        )
        deadline = time.monotonic() + wait_bound
        while True:
            row = self._read_generation_reservation(
                project_id, expected_revision, operation
            )
            if row is None:
                logical_call_id = self._try_insert_generation_reservation(
                    project_id, expected_revision, operation
                )
                if logical_call_id is not None:
                    return _GenerationReservationAcquisition(
                        logical_call_id=logical_call_id
                    )
                continue  # lost the insert race; re-read the winner's row
            status = str(row["status"])
            if status == "failed" and int(row["transport_attempt_count"] or 0) > 0:
                # Defense-in-depth: a reservation that ever reached the
                # transport layer can never be retryable as a known failure
                # (the upstream model may have completed and only the local
                # result was lost).  Treat it exactly like unknown_outcome
                # so a non-force caller fails closed.
                status = "unknown_outcome"
            if status == "completed":
                # The generation for this key already happened: replay the
                # winner's outcome instead of dispatching again.  Verify the
                # completion event revision so the caller can explain a
                # refresh (the current journey may be a later revision).
                return self._replay_completed_reservation(
                    project_id, expected_revision, operation, row
                )
            if status == "failed":
                # Known failure (no event persisted): a fresh logical call
                # may take over the key.
                logical_call_id = self._supersede_generation_reservation(
                    project_id,
                    expected_revision,
                    operation,
                    previous_call_id=str(row["logical_call_id"]),
                    note=f"supersedes failed call {row['logical_call_id']}",
                )
                if logical_call_id is not None:
                    return _GenerationReservationAcquisition(
                        logical_call_id=logical_call_id
                    )
                continue
            if status == "unknown_outcome":
                if not force:
                    raise MedicalWritingAuthoringJourneyConflictError(
                        "prefill generation for this revision is in an "
                        "unknown-outcome state from a prior call "
                        f"({row['logical_call_id']}); the state is preserved "
                        "and will not be redispatched automatically; retry "
                        "with force=True to start a new logical call"
                    )
                logical_call_id = self._supersede_generation_reservation(
                    project_id,
                    expected_revision,
                    operation,
                    previous_call_id=str(row["logical_call_id"]),
                    note=(
                        "supersedes unknown-outcome call "
                        f"{row['logical_call_id']}"
                    ),
                )
                if logical_call_id is not None:
                    return _GenerationReservationAcquisition(
                        logical_call_id=logical_call_id
                    )
                continue
            # status == "in_flight": wait for a terminal state within the
            # bounded window (the winner may still be enriching).
            if force:
                # Worker_03 corrective: force must never interrupt a live
                # call.  Fail fast with an accurate message naming the
                # in-flight owner instead of waiting out the bound and then
                # raising a misleading "retry with force=True" error.
                raise MedicalWritingAuthoringJourneyConflictError(
                    "prefill generation is already in flight for this "
                    f"revision (logical call {row['logical_call_id']}); "
                    "force cannot interrupt the live call; wait for the "
                    "owner to complete or, after the wait bound marks the "
                    "call unknown-outcome, retry with force=True"
                )
            if time.monotonic() >= deadline:
                # Worker_03 corrective: the deadline flip is bound to the
                # OBSERVED logical call id with a rowcount check so a stale
                # waiter can never flip a reservation that a newer owner
                # (or a completed event) superseded between read and
                # update.  The owner's own completion UPDATE is bound to
                # its logical call id and may still complete the same row.
                observed_call_id = str(row["logical_call_id"])
                now_iso = datetime.now(timezone.utc).isoformat()
                history = json.loads(str(row["attempt_history"] or "[]"))
                history.append(
                    {
                        "logical_call_id": observed_call_id,
                        "transport_attempt_count": int(
                            row["transport_attempt_count"] or 0
                        ),
                        "status": "in_flight",
                        "failure_note": row["failure_note"],
                        "updated_at": row["updated_at"],
                    }
                )
                with self._connect() as connection:
                    cursor = connection.execute(
                        "UPDATE "
                        "medical_writing_authoring_journey_generation_reservations "
                        "SET status = 'unknown_outcome', failure_note = ?, "
                        "attempt_history = ?, updated_at = ? "
                        "WHERE project_id = ? AND expected_revision = ? "
                        "AND operation = ? AND logical_call_id = ? "
                        "AND status = 'in_flight'",
                        (
                            _WAITER_DEADLINE_FLIP_NOTE,
                            json.dumps(history, ensure_ascii=False),
                            now_iso,
                            project_id,
                            expected_revision,
                            operation,
                            observed_call_id,
                        ),
                    )
                    connection.commit()
                row = self._read_generation_reservation(
                    project_id, expected_revision, operation
                )
                if row is not None and str(row["status"]) == "completed":
                    return self._replay_completed_reservation(
                        project_id, expected_revision, operation, row
                    )
                # When the flip was not applied, the observed call was
                # completed or superseded between our read and the update:
                # never flip a reservation we did not observe.  Either way
                # this caller's wait is exhausted and the observed call
                # outcome is unknown to it, so fail closed.
                raise MedicalWritingAuthoringJourneyConflictError(
                    "prefill generation reservation is still in flight "
                    "beyond the wait bound; the prior call outcome is "
                    "unknown and preserved; it will not be redispatched "
                    "automatically; retry with force=True to start a new "
                    "logical call"
                )
            time.sleep(min(0.1, max(0.02, wait_bound / 20.0)))

    def _mark_generation_reservation_dispatched(
        self,
        *,
        project_id: str,
        expected_revision: int,
        operation: str,
        logical_call_id: str,
    ) -> None:
        """Record the single physical transport attempt for this logical
        call right before dispatch.

        The AI-first prefill route is restricted to at most one upstream
        POST, so the attempt is recorded at dispatch time: a crash right
        around dispatch must be treated conservatively as one attempted
        POST (fail-closed telemetry).
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE "
                "medical_writing_authoring_journey_generation_reservations "
                "SET transport_attempt_count = 1, updated_at = ? "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
                "AND logical_call_id = ? AND status = 'in_flight'",
                (
                    now_iso,
                    project_id,
                    expected_revision,
                    operation,
                    logical_call_id,
                ),
            )
            connection.commit()
        if cursor.rowcount != 1:
            # Worker_03 corrective: this caller lost ownership of the
            # reservation before dispatch (a stale waiter marked it
            # unknown-outcome and a force call superseded it, or the owner
            # completed).  Refuse to dispatch a physical transport for a
            # reservation we no longer own: the at-most-one-transport
            # invariant per logical call holds only while the reservation
            # remains ours and in flight.
            raise MedicalWritingAuthoringJourneyConflictError(
                "generation reservation is no longer owned by this logical "
                f"call ({logical_call_id}) in flight state; dispatch aborted"
            )

    @staticmethod
    def _complete_generation_reservation(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        expected_revision: int,
        operation: str,
        logical_call_id: str,
        status: str,
        event_id: str,
    ) -> None:
        """Complete the reservation inside the caller's write transaction so
        the terminal reservation state and the generation event commit (or
        roll back) atomically.

        Worker_03 corrective: a waiter deadline may have flipped the same
        logical call to ``unknown_outcome`` under skewed wait bounds; the
        owner's completion still owns the row (logical-call-bound), and a
        ``completed`` status clears only the stale waiter flip note ("owner
        presumed interrupted") while the attempt history keeps the flip
        audit entry.  Supersede lineage notes are preserved on the
        completed row.
        """
        clear_flip_note = status == "completed"
        cursor = connection.execute(
            "UPDATE "
            "medical_writing_authoring_journey_generation_reservations "
            + (
                "SET status = ?, event_id = ?, "
                "failure_note = CASE WHEN failure_note = ? "
                "THEN NULL ELSE failure_note END, updated_at = ? "
                if clear_flip_note
                else "SET status = ?, event_id = ?, updated_at = ? "
            )
            + "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
            "AND logical_call_id = ?",
            (
                status,
                event_id,
                _WAITER_DEADLINE_FLIP_NOTE,
                datetime.now(timezone.utc).isoformat(),
                project_id,
                expected_revision,
                operation,
                logical_call_id,
            )
            if clear_flip_note
            else (
                status,
                event_id,
                datetime.now(timezone.utc).isoformat(),
                project_id,
                expected_revision,
                operation,
                logical_call_id,
            ),
        )
        if cursor.rowcount != 1:
            raise MedicalWritingAuthoringJourneyConflictError(
                "generation reservation disappeared before completion"
            )

    def _release_generation_reservation(
        self,
        *,
        project_id: str,
        expected_revision: int,
        operation: str,
        logical_call_id: str,
        status: str,
        note: str,
    ) -> None:
        """Release a reservation after the generation event was NOT
        persisted (the write transaction failed).

        Fail-closed classification (worker_02 corrective round 2): once a
        reservation has been marked dispatched (``transport_attempt_count
        > 0``) the upstream model may have completed and only the local
        result may have been lost, so every non-committed terminal path is
        ``unknown_outcome`` — regardless of whether the provider returned,
        raised, or the local event transaction failed.  Only a provably
        pre-dispatch failure (``transport_attempt_count == 0``) may be
        retryable as ``failed``.  The rule is re-applied from the persisted
        row so a stale caller cannot downgrade a dispatched attempt."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT transport_attempt_count FROM "
                "medical_writing_authoring_journey_generation_reservations "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
                "AND logical_call_id = ? AND status = 'in_flight'",
                (project_id, expected_revision, operation, logical_call_id),
            ).fetchone()
            if row is None:
                # Already terminal or superseded by a concurrent worker.
                return
            if status == "failed" and int(row["transport_attempt_count"] or 0) > 0:
                status = "unknown_outcome"
                note = f"{note}; transport attempt was dispatched, outcome unknown"
            connection.execute(
                "UPDATE "
                "medical_writing_authoring_journey_generation_reservations "
                "SET status = ?, failure_note = ?, updated_at = ? "
                "WHERE project_id = ? AND expected_revision = ? AND operation = ? "
                "AND logical_call_id = ? AND status = 'in_flight'",
                (
                    status,
                    note,
                    now_iso,
                    project_id,
                    expected_revision,
                    operation,
                    logical_call_id,
                ),
            )
            connection.commit()

    def _persist_update(
        self,
        connection: sqlite3.Connection,
        state: MedicalWritingAuthoringJourney,
        *,
        expected_revision: int,
        event_type: str,
        actor: str,
        idempotency_key: str,
        request_sha256: str,
        detail: dict[str, Any],
    ) -> str:
        current = _load_authoring_journey_payload(
            self._current_row(connection, state.project_id)["payload_json"]
        )
        self._ensure_reservation_allows_event(current, event_type)
        payload_json = state.model_dump_json()
        cursor = connection.execute(
            """
            UPDATE medical_writing_authoring_journeys
            SET revision = ?, state_sha256 = ?, updated_at = ?, payload_json = ?
            WHERE project_id = ? AND revision = ?
            """,
            (
                state.revision,
                _payload_sha256(state.model_dump(mode="json")),
                state.updated_at.isoformat(),
                payload_json,
                state.project_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise MedicalWritingAuthoringJourneyConflictError(
                "authoring journey changed before the update was committed"
            )
        return self._insert_event(
            connection,
            state=state,
            event_type=event_type,
            actor=actor,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            detail=detail,
        )

    @staticmethod
    def _ensure_reservation_allows_event(
        current: MedicalWritingAuthoringJourney,
        event_type: str,
    ) -> None:
        if current.document_creation_reservation is None:
            return
        if event_type in {
            "authoring_journey_document_created",
            "authoring_journey_document_creation_reservation_released",
        }:
            return
        raise MedicalWritingAuthoringJourneyConflictError(
            "authoring journey is locked by an active writing-document creation reservation"
        )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        state: MedicalWritingAuthoringJourney,
        event_type: str,
        actor: str,
        idempotency_key: str,
        request_sha256: str,
        detail: dict[str, Any],
    ) -> str:
        event_id = "mwjourney_event_" + hashlib.sha256(
            f"{state.project_id}|{event_type}|{idempotency_key}".encode("utf-8")
        ).hexdigest()[:24]
        connection.execute(
            """
            INSERT INTO medical_writing_authoring_journey_events(
                event_id, project_id, journey_id, revision, event_type,
                actor, idempotency_key, request_sha256, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                state.project_id,
                state.journey_id,
                state.revision,
                event_type,
                actor,
                idempotency_key,
                request_sha256,
                state.updated_at.isoformat(),
                json.dumps(detail, ensure_ascii=False, sort_keys=True),
            ),
        )
        return event_id


def _changed_fields(prefix: str, current: dict[str, Any], proposed: dict[str, Any]) -> list[str]:
    return sorted(
        f"{prefix}.{key}"
        for key in set(current) | set(proposed)
        if current.get(key) != proposed.get(key)
    )


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_study_definition_picos(picos: Any) -> Any:
    """Return the StudyDefinition view of PICOS without mutating author input.

    Structured intervention rules are authoritative. Their legacy fields remain
    editable compatibility values in the authoring journey, but StudyDefinition
    facts, hashes, and binding checks must all use the same deterministic
    projection.
    """
    if picos is None:
        return None
    rules = getattr(picos, "intervention_rules", None)
    if (
        rules is None
        or getattr(rules, "authority", None)
        != InterventionRulesAuthority.STRUCTURED
    ):
        return picos
    return picos.model_copy(
        update=picos.project_legacy_intervention_fields(),
        deep=True,
    )


def _study_definition_facts_sha256(framing: Any, picos: Any) -> str:
    canonical_picos = _canonical_study_definition_picos(picos)
    return _payload_sha256(
        {
            "framing": framing.model_dump(mode="json"),
            "picos": (
                canonical_picos.model_dump(mode="json")
                if canonical_picos is not None
                else {}
            ),
        }
    )


def _study_schema_epoch_kind(
    label: str, *, first: bool = False, last: bool = False
) -> str:
    normalized = label.strip().lower()
    if any(token in normalized for token in ("筛选", "screen")):
        return "screening"
    if any(token in normalized for token in ("导入", "run-in", "run in")):
        return "run_in"
    if any(
        token in normalized
        for token in (
            "转组",
            "切换治疗",
            "治疗切换",
            "switch treatment",
            "treatment switch",
            "crossover",
            "cross-over",
        )
    ):
        return "treatment_switch"
    if any(
        token in normalized
        for token in (
            "开放标签延展",
            "开放延展",
            "长期延展",
            "open-label extension",
            "open label extension",
            "ole",
        )
    ):
        return "extension_period"
    if any(token in normalized for token in ("随访", "follow")):
        return "follow_up"
    if any(token in normalized for token in ("治疗", "给药", "treatment", "dose")):
        return "treatment"
    if first:
        return "entry"
    if last:
        return "end"
    return "other"


_PHASE1_MODULE_ALIASES = (
    ("sad", ("sad", "单次给药剂量递增", "单剂量递增")),
    ("mad", ("mad", "多次给药剂量递增", "多剂量递增")),
    ("food_effect", ("食物影响", "food effect")),
    ("mass_balance", ("物质平衡", "mass balance")),
    ("hepatic_impairment", ("肝功能不全", "肝损伤", "hepatic impairment")),
    ("renal_impairment", ("肾功能不全", "肾损伤", "renal impairment")),
    ("ddi", ("ddi", "药物相互作用", "drug-drug interaction")),
    (
        "first_in_patient",
        ("首次患者", "first-in-patient", "first in patient", "fip"),
    ),
)


def _study_schema_phase1_modules(design_projection: Any) -> list[str]:
    """Read Phase I Part selection only from NormalizedDesignProjection."""

    modules: list[str] = []
    aliases = {
        alias.lower().replace("-", "_").replace(" ", "_"): module
        for module, values in _PHASE1_MODULE_ALIASES
        for alias in (module, *values)
    }
    for part in design_projection.design_view.phase1_parts:
        raw_code = str(part.part_code or "").strip().lower()
        normalized = raw_code.replace("-", "_").replace(" ", "_")
        module = aliases.get(normalized, normalized)
        if module and module not in modules:
            modules.append(module)
    return modules


def _propose_phase1_study_schema(
    *,
    project_id: str,
    framing: Any,
    picos: Any,
    design_projection: Any,
    facts_sha256: str,
    modules: list[str],
    now: datetime,
) -> MedicalWritingStudySchemaDefinition:
    def binding(path: str) -> list[MedicalWritingStudySchemaSourceBinding]:
        return [MedicalWritingStudySchemaSourceBinding(study_definition_path=path)]

    module_labels = {
        "sad": "单次给药剂量递增（SAD）",
        "mad": "多次给药剂量递增（MAD）",
        "food_effect": "食物影响",
        "mass_balance": "物质平衡",
        "hepatic_impairment": "肝功能不全",
        "renal_impairment": "肾功能不全",
        "ddi": "药物相互作用（DDI）",
        "first_in_patient": "首次患者",
    }
    parts: list[MedicalWritingStudySchemaPart] = []
    nodes: list[MedicalWritingStudySchemaNode] = []
    edges: list[MedicalWritingStudySchemaEdge] = []

    def add_node(
        *,
        module: str,
        part_id: str,
        suffix: str,
        order: int,
        node_kind: str,
        label: str,
        detail_lines: list[str] | None = None,
        lane_order: int = 0,
        source_path: str = "framing.structured_design.phase1_parts",
    ) -> str:
        node_id = f"{module}_{suffix}"
        nodes.append(
            MedicalWritingStudySchemaNode(
                node_id=node_id,
                part_id=part_id,
                order=order,
                lane_order=lane_order,
                node_kind=node_kind,
                label=label,
                detail_lines=detail_lines or [],
                fact_status="extracted_candidate",
                source_bindings=binding(source_path),
            )
        )
        return node_id

    def add_edge(
        *,
        edge_id: str,
        source: str,
        target: str,
        edge_kind: str = "participant_flow",
        label: str = "",
        source_path: str = "framing.structured_design.phase1_parts",
    ) -> None:
        edges.append(
            MedicalWritingStudySchemaEdge(
                edge_id=edge_id,
                from_node_id=source,
                to_node_id=target,
                edge_kind=edge_kind,
                label=label,
                fact_status="extracted_candidate",
                source_bindings=binding(source_path),
            )
        )

    design_view = design_projection.design_view
    src_named = design_view.src_planned is True
    sequential_parts = bool(design_view.phase1_sequence)
    gate_label = "SRC安全性审查" if src_named else "安全性审查/进入门"
    part_by_module = {
        str(part.part_code).strip().lower().replace("-", "_"): part
        for part in design_view.phase1_parts
    }
    epochs = list(getattr(picos, "study_epochs", []) or [])
    screening_label = next(
        (item for item in epochs if "筛选" in item or "screen" in item.lower()),
        "筛选期",
    )
    follow_up_label = next(
        (item for item in epochs if "随访" in item or "follow" in item.lower()),
        "安全性随访期",
    )

    for part_index, module in enumerate(modules):
        typed_part = part_by_module.get(module)
        part_id = f"part_{module}"
        label = (
            typed_part.part_label
            if typed_part is not None and typed_part.part_label
            else module_labels[module]
        )
        parts.append(
            MedicalWritingStudySchemaPart(
                part_id=part_id,
                order=part_index,
                label=f"Part {chr(65 + part_index)}：{label}",
                flow_direction="left_to_right",
                source_bindings=binding(
                    "framing.structured_design.phase1_parts"
                ),
            )
        )
        screening = add_node(
            module=module,
            part_id=part_id,
            suffix="screening",
            order=0,
            node_kind="screening",
            label=screening_label,
            detail_lines=(
                [
                    (
                        "前一部分审查完成后启动（待确认）"
                        if sequential_parts
                        else "与其他部分的启动关系待确认"
                    )
                ]
                if part_index > 0
                else []
            ),
            source_path="picos.study_epochs",
        )

        if module in {"sad", "mad"}:
            first_cohort = add_node(
                module=module,
                part_id=part_id,
                suffix="initial_cohort",
                order=1,
                node_kind="dose_cohort",
                label="起始剂量队列",
                detail_lines=[
                    item
                    for item in (
                        typed_part.population if typed_part else "",
                        typed_part.cohort_dose if typed_part else "",
                    )
                    if item
                ],
                source_path="framing.structured_design.phase1_parts",
            )
            gate = add_node(
                module=module,
                part_id=part_id,
                suffix="safety_gate",
                order=2,
                node_kind="decision_gate",
                label=gate_label,
                detail_lines=[
                    typed_part.transition_dependencies
                    if typed_part
                    else ""
                ],
                source_path="framing.structured_design.src_planned",
            )
            later_cohort = add_node(
                module=module,
                part_id=part_id,
                suffix="later_cohort",
                order=3,
                node_kind="dose_cohort",
                label="后续剂量队列",
                detail_lines=[
                    typed_part.cohort_dose if typed_part else ""
                ],
                source_path="framing.structured_design.phase1_parts",
            )
            follow_up = add_node(
                module=module,
                part_id=part_id,
                suffix="follow_up",
                order=4,
                node_kind="follow_up",
                label=follow_up_label,
                source_path="picos.study_epochs",
            )
            add_edge(
                edge_id=f"{module}_screen_to_initial",
                source=screening,
                target=first_cohort,
            )
            add_edge(
                edge_id=f"{module}_initial_to_gate",
                source=first_cohort,
                target=gate,
                edge_kind="activation_dependency",
                label="审查",
                source_path="framing.structured_design.src_planned",
            )
            add_edge(
                edge_id=f"{module}_gate_to_later",
                source=gate,
                target=later_cohort,
                edge_kind="activation_dependency",
                label="通过",
                source_path="framing.structured_design.src_planned",
            )
            add_edge(
                edge_id=f"{module}_initial_to_followup",
                source=first_cohort,
                target=follow_up,
                edge_kind="follow_up",
                source_path="picos.study_epochs",
            )
            add_edge(
                edge_id=f"{module}_later_to_followup",
                source=later_cohort,
                target=follow_up,
                edge_kind="follow_up",
                source_path="picos.study_epochs",
            )
            continue

        module_node_specs = {
            "food_effect": (
                "空腹/餐后给药条件（设计待确认）",
                "treatment",
                ["序列、周期和洗脱期设置待确认"],
                "食物影响PK评价",
            ),
            "mass_balance": (
                "物质平衡给药",
                "treatment",
                ["标记方式、剂量和采样窗口待确认"],
                "回收率与排泄途径评价",
            ),
            "hepatic_impairment": (
                "肝功能不全与匹配对照队列",
                "dose_cohort",
                ["分层标准和匹配条件待确认"],
                "PK/安全性评价",
            ),
            "renal_impairment": (
                "肾功能不全与匹配对照队列",
                "dose_cohort",
                ["分层标准和匹配条件待确认"],
                "PK/安全性评价",
            ),
            "ddi": (
                "单药与联用阶段（设计待确认）",
                "treatment",
                ["底物/抑制剂、顺序和洗脱期待确认"],
                "药物相互作用PK评价",
            ),
            "first_in_patient": (
                "首次患者队列（待确认）",
                "dose_cohort",
                ["剂量、队列层级和进入标准待确认"],
                "患者PK/PD与安全性评价",
            ),
        }
        core_label, core_kind, detail_lines, assessment_label = module_node_specs[module]
        core = add_node(
            module=module,
            part_id=part_id,
            suffix="core",
            order=1,
            node_kind=core_kind,
            label=core_label,
            detail_lines=detail_lines,
            source_path="picos.intervention_summary",
        )
        assessment = add_node(
            module=module,
            part_id=part_id,
            suffix="assessment",
            order=2,
            node_kind="other",
            label=assessment_label,
            source_path="framing.structured_design.phase1_parts",
        )
        follow_up = add_node(
            module=module,
            part_id=part_id,
            suffix="follow_up",
            order=3,
            node_kind="follow_up",
            label=follow_up_label,
            source_path="framing.structured_design.phase1_parts",
        )
        add_edge(
            edge_id=f"{module}_screen_to_core",
            source=screening,
            target=core,
        )
        add_edge(
            edge_id=f"{module}_core_to_assessment",
            source=core,
            target=assessment,
        )
        add_edge(
            edge_id=f"{module}_assessment_to_followup",
            source=assessment,
            target=follow_up,
            edge_kind="follow_up",
            source_path="framing.structured_design.phase1_parts",
        )

    return MedicalWritingStudySchemaDefinition(
        schema_id="mwschema_proposal_"
        + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20],
        revision=1,
        source_facts_sha256=facts_sha256,
        status="draft",
        title="I期研究设计概况",
        parts=parts,
        nodes=nodes,
        edges=edges,
        annotations=[
            "各Part按已确认模块清单顺序展示，实际启动关系待确认；剂量、队列人数、哨兵设置和进入标准未被系统虚构。"
        ],
        state_sha256="0" * 64,
        updated_at=now,
        updated_by="system_proposal",
    )


def _propose_crossover_study_schema(
    *,
    project_id: str,
    picos: Any,
    design_projection: Any,
    facts_sha256: str,
    now: datetime,
) -> MedicalWritingStudySchemaDefinition:
    """Project a true period/sequence crossover flow, not a treatment switch."""

    crossover = design_projection.design_view.crossover

    def binding(path: str) -> list[MedicalWritingStudySchemaSourceBinding]:
        return [MedicalWritingStudySchemaSourceBinding(study_definition_path=path)]

    path = "framing.structured_design.crossover"
    part = MedicalWritingStudySchemaPart(
        part_id="crossover",
        order=0,
        label="交叉研究流程",
        flow_direction="left_to_right",
        source_bindings=binding(path),
    )
    nodes: list[MedicalWritingStudySchemaNode] = [
        MedicalWritingStudySchemaNode(
            node_id="crossover_screening",
            part_id=part.part_id,
            order=0,
            node_kind="screening",
            label="筛选期",
            fact_status="extracted_candidate",
            source_bindings=binding("picos.study_epochs"),
        ),
        MedicalWritingStudySchemaNode(
            node_id="crossover_randomization",
            part_id=part.part_id,
            order=1,
            node_kind="randomization",
            label="随机分配交叉序列",
            detail_lines=list(crossover.sequences),
            fact_status="extracted_candidate",
            source_bindings=binding(path),
        ),
    ]
    edges: list[MedicalWritingStudySchemaEdge] = [
        MedicalWritingStudySchemaEdge(
            edge_id="crossover_screen_to_randomization",
            from_node_id="crossover_screening",
            to_node_id="crossover_randomization",
            fact_status="extracted_candidate",
            source_bindings=binding(path),
        )
    ]
    prior = "crossover_randomization"
    for index, period in enumerate(crossover.periods):
        period_node = f"crossover_period_{index + 1}"
        nodes.append(
            MedicalWritingStudySchemaNode(
                node_id=period_node,
                part_id=part.part_id,
                order=2 + index * 2,
                node_kind="treatment",
                label=period,
                detail_lines=[
                    "；".join(crossover.sequences),
                    crossover.period_sequence_analysis,
                ],
                fact_status="extracted_candidate",
                source_bindings=binding(path),
            )
        )
        edges.append(
            MedicalWritingStudySchemaEdge(
                edge_id=f"edge_{prior}_{period_node}",
                from_node_id=prior,
                to_node_id=period_node,
                edge_kind="participant_flow",
                fact_status="extracted_candidate",
                source_bindings=binding(path),
            )
        )
        prior = period_node
        if index < len(crossover.periods) - 1:
            washout_node = f"crossover_washout_{index + 1}"
            nodes.append(
                MedicalWritingStudySchemaNode(
                    node_id=washout_node,
                    part_id=part.part_id,
                    order=3 + index * 2,
                        node_kind="other",
                    label="洗脱期",
                    detail_lines=[
                        crossover.washout_strategy,
                        crossover.carryover_assessment,
                    ],
                    fact_status="extracted_candidate",
                    source_bindings=binding(path),
                )
            )
            edges.append(
                MedicalWritingStudySchemaEdge(
                    edge_id=f"edge_{prior}_{washout_node}",
                    from_node_id=prior,
                    to_node_id=washout_node,
                    edge_kind="participant_flow",
                    fact_status="extracted_candidate",
                    source_bindings=binding(path),
                )
            )
            prior = washout_node
    nodes.append(
        MedicalWritingStudySchemaNode(
            node_id="crossover_follow_up",
            part_id=part.part_id,
            order=2 + len(crossover.periods) * 2,
            node_kind="follow_up",
            label="安全性随访",
            fact_status="extracted_candidate",
            source_bindings=binding("picos.study_epochs"),
        )
    )
    edges.append(
        MedicalWritingStudySchemaEdge(
            edge_id=f"edge_{prior}_crossover_follow_up",
            from_node_id=prior,
            to_node_id="crossover_follow_up",
            edge_kind="follow_up",
            fact_status="extracted_candidate",
            source_bindings=binding(path),
        )
    )
    return MedicalWritingStudySchemaDefinition(
        schema_id="mwschema_proposal_"
        + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20],
        revision=1,
        source_facts_sha256=facts_sha256,
        status="draft",
        title="交叉研究设计概况",
        parts=[part],
        nodes=nodes,
        edges=edges,
        annotations=[
            "交叉序列、周期、洗脱及残留效应分析均来自已确认的结构化设计。"
        ],
        state_sha256="0" * 64,
        updated_at=now,
        updated_by="system_proposal",
    )


def _study_schema_comparison_payload(
    schema: MedicalWritingStudySchemaDefinition | None,
) -> dict[str, Any]:
    if schema is None:
        return {}
    return schema.model_dump(
        mode="json",
        exclude={"schema_id", "revision", "state_sha256", "updated_at", "updated_by"},
    )


def _replace_study_definition_schema(
    definition: MedicalWritingStudyDefinition,
    schema: MedicalWritingStudySchemaDefinition,
    *,
    actor: str,
    now: datetime,
) -> MedicalWritingStudyDefinition:
    updated = definition.model_copy(
        update={
            "revision": definition.revision + 1,
            "schema_version": "medical_writing_study_definition_v2",
            "study_schema": schema,
            "updated_at": now,
            "updated_by": actor,
        },
        deep=True,
    )
    payload = updated.model_dump(mode="json", exclude={"state_sha256"})
    return updated.model_copy(
        update={"state_sha256": _payload_sha256(payload)}, deep=True
    )


def _study_fact_value_hashes(framing: Any, picos: Any) -> dict[str, str]:
    framing_payload = framing.model_dump(mode="json")
    canonical_picos = _canonical_study_definition_picos(picos)
    picos_payload = (
        canonical_picos.model_dump(mode="json")
        if canonical_picos is not None
        else {}
    )
    hashes: dict[str, str] = {}
    for prefix, payload in (("framing", framing_payload), ("picos", picos_payload)):
        for path, value in _iter_study_fact_state_values(prefix, payload):
            hashes[path] = _payload_sha256(value)
    return hashes


def _capture_extracted_value_hashes(
    synopsis_import: MedicalWritingSynopsisImport,
) -> MedicalWritingSynopsisImport:
    fact_value_hashes = _study_fact_value_hashes(
        synopsis_import.proposed_framing,
        synopsis_import.proposed_picos,
    )
    return synopsis_import.model_copy(
        update={
            "field_extracted_value_sha256": fact_value_hashes,
            "synopsis_bound_value_sha256": fact_value_hashes,
        },
        deep=True,
    )


def _edited_imported_fact_paths(
    synopsis_import: MedicalWritingSynopsisImport,
    framing: Any,
    picos: Any,
) -> list[str]:
    current_hashes = _study_fact_value_hashes(framing, picos)
    return sorted(
        path
        for path, value_hash in current_hashes.items()
        if synopsis_import.field_extracted_value_sha256.get(path) != value_hash
    )


_NESTED_STUDY_FACT_ROOTS = {
    "framing.product_profile",
    "framing.structured_design",
    "picos.intervention_rules",
}

_STUDY_FACT_METADATA_FIELDS = {"schema_version"}

_UNRESOLVED_STUDY_FACT_SENTINELS = {
    "unknown",
    "undecided",
    "not_assessed",
    "not_started",
}


def _is_unresolved_study_fact_sentinel(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.strip().lower() in _UNRESOLVED_STUDY_FACT_SENTINELS
    )


def _has_material_study_fact_value(value: Any) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, dict):
        return any(_has_material_study_fact_value(item) for item in value.values())
    return bool(value)


def _iter_study_fact_state_values(
    prefix: str,
    payload: dict[str, Any],
):
    """Yield governed top-level facts plus material nested design facts.

    ProtocolAssemblyPlan and the dynamic template consume nested structured
    design, product-profile, and intervention-rule paths. The author confirms
    those objects as part of the framing/PICOS stage, so their material nested
    paths must carry the same auditable fact state instead of appearing absent
    at greenfield document creation.
    """

    def walk(path: str, value: Any):
        if not isinstance(value, dict):
            return
        for child_name, child_value in value.items():
            if child_name in _STUDY_FACT_METADATA_FIELDS:
                continue
            child_path = f"{path}.{child_name}"
            if not _has_material_study_fact_value(child_value):
                continue
            yield child_path, child_value
            yield from walk(child_path, child_value)

    for field_name, value in payload.items():
        if prefix == "picos" and field_name == "field_applicability":
            continue
        path = f"{prefix}.{field_name}"
        yield path, value
        if path in _NESTED_STUDY_FACT_ROOTS:
            yield from walk(path, value)


def _build_study_definition(
    *,
    project_id: str,
    revision: int,
    origin: str,
    framing: Any,
    picos: Any,
    synopsis_import: MedicalWritingSynopsisImport | None,
    confirmed_stages: set[str],
    actor: str,
    now: datetime,
    created_at: datetime | None = None,
    current_study_schema: MedicalWritingStudySchemaDefinition | None = None,
    confirmed_paths: set[str] | None = None,
) -> MedicalWritingStudyDefinition:
    framing_payload = framing.model_dump(mode="json")
    canonical_picos = _canonical_study_definition_picos(picos)
    picos_payload = (
        canonical_picos.model_dump(mode="json")
        if canonical_picos is not None
        else {}
    )
    imported = synopsis_import if synopsis_import and synopsis_import.source else None
    source_artifact_ids = [imported.source.source_id] if imported else []
    evidence_spans = {
        item.span_id: item for item in (imported.evidence_spans if imported else [])
    }
    field_evidence = imported.field_evidence_span_ids if imported else {}
    extracted_value_hashes = (
        imported.field_extracted_value_sha256 if imported else {}
    )
    import_was_reviewed = bool(
        imported
        and imported.status == "confirmed"
        and imported.confirmed_by
        and imported.confirmed_at
    )
    field_states: dict[str, MedicalWritingStudyFactState] = {}
    explicitly_confirmed = confirmed_paths or set()
    current_fact_hashes = _study_fact_value_hashes(framing, picos)

    for prefix, payload in (("framing", framing_payload), ("picos", picos_payload)):
        for path, value in _iter_study_fact_state_values(prefix, payload):
            field_name = path[len(prefix) + 1 :]
            is_top_level = "." not in field_name
            unresolved_sentinel = _is_unresolved_study_fact_sentinel(value)
            has_value = (
                (bool(value) or value is False or value == 0)
                and not unresolved_sentinel
            )
            applicability = (
                picos_payload.get("field_applicability", {}).get(field_name, {})
                if prefix == "picos" and is_top_level
                else {}
            )
            source_hash_path = path
            extracted_value_hash = extracted_value_hashes.get(path, "")
            if not extracted_value_hash:
                source_hash_path = next(
                    (
                        root
                        for root in _NESTED_STUDY_FACT_ROOTS
                        if path.startswith(f"{root}.")
                        and extracted_value_hashes.get(root)
                    ),
                    path,
                )
                extracted_value_hash = extracted_value_hashes.get(
                    source_hash_path, ""
                )
            current_value_hash = (
                current_fact_hashes.get(source_hash_path, "")
                if source_hash_path != path
                else _payload_sha256(value)
            )
            value_matches_extraction = bool(
                extracted_value_hash
                and extracted_value_hash == current_value_hash
            )
            evidence: list[MedicalWritingStudyFactEvidence] = []
            if imported and value_matches_extraction:
                evidence_path = path
                if not field_evidence.get(evidence_path):
                    evidence_path = next(
                        (
                            root
                            for root in _NESTED_STUDY_FACT_ROOTS
                            if path.startswith(f"{root}.")
                            and field_evidence.get(root)
                            and extracted_value_hashes.get(root)
                            == current_fact_hashes.get(root)
                        ),
                        source_hash_path,
                    )
                for span_id in field_evidence.get(evidence_path, []):
                    span = evidence_spans.get(span_id)
                    if span is None:
                        continue
                    evidence.append(
                        MedicalWritingStudyFactEvidence(
                            source_id=span.source_id,
                            extraction_revision=imported.source.extraction_revision,
                            evidence_span_id=span.span_id,
                            locator=span.locator,
                            quote_sha256=span.source_text_sha256,
                        )
                    )
            has_source_evidence = bool(evidence)
            nested_confirmation_pending = bool(
                path == "picos.assessment_instruments"
                and any(
                    item.get("confirmation_status") != "confirmed"
                    for item in (value or [])
                )
            )
            path_was_confirmed = (
                prefix in confirmed_stages or path in explicitly_confirmed
            )
            if (
                applicability.get("status") == "not_applicable"
                and path_was_confirmed
            ):
                status = "not_applicable"
            elif unresolved_sentinel:
                status = "deferred"
            elif (
                path_was_confirmed
                and has_value
                and not nested_confirmation_pending
            ):
                status = "confirmed"
            elif not has_value:
                status = "missing"
            elif has_source_evidence:
                status = "extracted_candidate"
            else:
                status = "manual_candidate"
            if import_was_reviewed and extracted_value_hash and not value_matches_extraction:
                value_origin = "medical_manager_edit"
            elif has_source_evidence:
                value_origin = "source_extraction"
            else:
                value_origin = "manual_entry"
            if value_origin == "medical_manager_edit":
                reviewed_by = actor
                reviewed_at = now
            elif import_was_reviewed and has_value:
                reviewed_by = imported.confirmed_by
                reviewed_at = imported.confirmed_at
            else:
                reviewed_by = ""
                reviewed_at = None
            field_states[path] = MedicalWritingStudyFactState(
                status=status,
                evidence=evidence,
                value_origin=value_origin,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                confirmed_by=actor if status in {"confirmed", "not_applicable"} else "",
                confirmed_at=now if status in {"confirmed", "not_applicable"} else None,
            )

    unresolved = sorted(
        path
        for path, state in field_states.items()
        if state.status not in {"confirmed", "not_applicable"}
    )
    canonical_origin = (
        "imported_synopsis" if origin == "synopsis_import" else origin
    )
    synopsis_fact_drift = bool(
        imported
        and any(
            imported.synopsis_bound_value_sha256.get(path) != value_hash
            for path, value_hash in current_fact_hashes.items()
        )
    )
    use_imported_synopsis = bool(
        imported
        and imported.proposed_synopsis_text
        and not synopsis_fact_drift
    )
    facts_sha256 = _study_definition_facts_sha256(framing, picos)
    study_schema = current_study_schema
    if study_schema is not None and study_schema.source_facts_sha256 != facts_sha256:
        study_schema = study_schema.model_copy(
            update={
                "revision": study_schema.revision + 1,
                "status": "stale",
                "updated_at": now,
                "updated_by": actor,
            },
            deep=True,
        )
        study_schema = study_schema.model_copy(
            update={"state_sha256": study_schema_state_sha256(study_schema)}, deep=True
        )
    definition_payload = {
        "definition_id": "mwdefinition_"
        + hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:20],
        "project_id": project_id,
        "revision": revision,
        "schema_version": "medical_writing_study_definition_v2",
        "origin": canonical_origin,
        "framing": framing_payload,
        "picos": picos_payload,
        "study_schema": (
            study_schema.model_dump(mode="json") if study_schema is not None else None
        ),
        "synopsis_text": (
            imported.proposed_synopsis_text
            if use_imported_synopsis
            else _render_protocol_synopsis(framing_payload, picos_payload)
        ),
        "synopsis_origin": (
            imported.proposed_synopsis_origin
            if use_imported_synopsis
            else "deterministic_projection"
        ),
        "field_states": {
            key: value.model_dump(mode="json") for key, value in field_states.items()
        },
        "source_artifact_ids": source_artifact_ids,
        "unresolved_paths": unresolved,
        "created_at": (created_at or now).isoformat(),
        "updated_at": now.isoformat(),
        "updated_by": actor,
    }
    definition_payload["state_sha256"] = _payload_sha256(definition_payload)
    return MedicalWritingStudyDefinition.model_validate(definition_payload)


def _merge_prefill_adoption_field_states(
    *,
    previous: MedicalWritingStudyDefinition,
    rebuilt: MedicalWritingStudyDefinition,
    changed_paths: list[str],
    actor: str,
    now: datetime,
) -> MedicalWritingStudyDefinition:
    """Keep prior fact governance while confirming fields adopted by a medical manager."""
    changed = set(changed_paths)

    def _path_affected(path: str) -> bool:
        if path in changed:
            return True
        # Adopting a structured root (e.g. framing.structured_design) must also
        # confirm nested leaf facts referenced by greenfield section seeds.
        return any(path.startswith(f"{root}.") for root in changed)

    merged_states: dict[str, MedicalWritingStudyFactState] = {}
    for path, rebuilt_state in rebuilt.field_states.items():
        previous_state = previous.field_states.get(path)
        if _path_affected(path):
            evidence = (
                previous_state.evidence
                if previous_state is not None
                else rebuilt_state.evidence
            )
            status = (
                "not_applicable"
                if rebuilt_state.status == "not_applicable"
                else "confirmed"
            )
            # Unresolved sentinels remain deferred even under a root adopt.
            if rebuilt_state.status == "deferred":
                merged_states[path] = rebuilt_state
                continue
            merged_states[path] = MedicalWritingStudyFactState(
                status=status,
                evidence=evidence,
                value_origin="medical_manager_edit",
                reviewed_by=actor,
                reviewed_at=now,
                confirmed_by=actor,
                confirmed_at=now,
            )
        elif previous_state is not None:
            # Stage-complete rebuild may newly confirm required fields that were
            # only pending before; prefer the upgraded confirmed/N-A state.
            if (
                rebuilt_state.status in {"confirmed", "not_applicable"}
                and previous_state.status not in {"confirmed", "not_applicable"}
            ):
                merged_states[path] = rebuilt_state
            else:
                merged_states[path] = previous_state
        else:
            merged_states[path] = rebuilt_state

    unresolved = sorted(
        path
        for path, state in merged_states.items()
        if state.status not in {"confirmed", "not_applicable"}
    )
    source_artifact_ids = list(
        dict.fromkeys(
            [*previous.source_artifact_ids, *rebuilt.source_artifact_ids]
        )
    )
    updated = rebuilt.model_copy(
        update={
            "field_states": merged_states,
            "source_artifact_ids": source_artifact_ids,
            "unresolved_paths": unresolved,
        },
        deep=True,
    )
    payload = updated.model_dump(mode="json", exclude={"state_sha256"})
    return updated.model_copy(
        update={"state_sha256": _payload_sha256(payload)},
        deep=True,
    )


def _render_protocol_synopsis(
    framing: dict[str, Any], picos: dict[str, Any]
) -> str:
    """Project confirmed facts into a reviewable synopsis without inventing prose."""
    rows: list[tuple[str, str]] = []

    def add(label: str, value: Any) -> None:
        if isinstance(value, list):
            text = "；".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value or "").strip()
        if text:
            rows.append((label, text))

    add("研究题目", framing.get("document_title"))
    add("方案编号", framing.get("protocol_id"))
    add("方案版本", framing.get("version"))
    add("研究分期", framing.get("study_phase"))
    add("适应症", framing.get("indication"))
    add("内在研究目的", framing.get("intrinsic_objectives"))
    add("试验药物", framing.get("investigational_product"))
    add("靶点/作用机制", framing.get("target_mechanism"))
    add("总体研究设计", _project_design_synopsis_from_dict(framing))
    add("目标研究人群", picos.get("population_summary") or framing.get("population_intent"))
    add("入选标准模块", picos.get("inclusion_modules"))
    add("排除标准模块", picos.get("exclusion_modules"))
    add("试验干预", picos.get("intervention_summary"))
    add("剂量与给药方案", picos.get("intervention_dose_regimen"))
    add("对照", picos.get("comparator_summary"))
    add("主要终点", picos.get("primary_endpoint"))
    add("关键次要终点", picos.get("key_secondary_endpoints"))
    add("安全性终点", picos.get("safety_endpoints"))
    add("特别关注的不良事件", picos.get("aesi_definitions"))
    add("研究时期", picos.get("study_epochs"))
    add("访视策略", picos.get("visit_strategy"))
    add("样本量策略", picos.get("sample_size_strategy"))
    add("统计分析策略", picos.get("statistical_strategy"))
    interim_text = _project_interim_synopsis_from_dict(framing, picos)
    if interim_text:
        add("期中分析", interim_text)
    return "\n".join(f"{label}：{value}" for label, value in rows)


def _project_design_synopsis_from_dict(framing: dict[str, Any]) -> str:
    """Prefer structured_design fields for the design synopsis row.

    Mirrors the company-template helper but works on the plain-dict framing
    payload used by the lightweight synopsis renderer. Falls back to the
    legacy design_pattern text when no structured field is decided.
    """
    structured = framing.get("structured_design") or {}
    parts: list[str] = []
    randomization_label = {
        "randomized": "随机化",
        "non_randomized": "非随机化",
    }.get(str(structured.get("randomization_mode") or ""))
    if randomization_label:
        details = str(structured.get("randomization_details") or "").strip()
        parts.append(f"{randomization_label}（{details}）" if details else randomization_label)
    blinding_label = {
        "open_label": "开放标签",
        "single_blind": "单盲",
        "double_blind": "双盲",
        "triple_blind": "三盲",
    }.get(str(structured.get("blinding_mode") or ""))
    if blinding_label:
        parts.append(blinding_label)
    comparator_label = {
        "placebo": "安慰剂对照",
        "active": "活性对照",
        "none_or_dose_escalation": "无平行对照/剂量递增",
    }.get(str(structured.get("comparator_type") or ""))
    if comparator_label:
        intervention = str(structured.get("comparator_intervention") or "").strip()
        parts.append(f"{comparator_label}（{intervention}）" if intervention else comparator_label)
    for key in ("assignment_model", "center_model"):
        value = str(structured.get(key) or "").strip()
        if value:
            parts.append(value)
    structured_text = "；".join(parts)
    legacy_text = str(framing.get("design_pattern") or "").strip()
    return structured_text or legacy_text


def _project_interim_synopsis_from_dict(
    framing: dict[str, Any], picos: dict[str, Any]
) -> str:
    """Project the interim analysis row from structured or legacy facts.

    Returns empty string when the row should be omitted. Planned True shows
    structured detail; Planned False suppresses; undecided falls back to
    legacy text detection only.
    """
    structured = framing.get("structured_design") or {}
    interim = structured.get("interim_analysis") or {}
    planned = interim.get("planned")
    if planned is False:
        return ""
    statistical_text = str(picos.get("statistical_strategy") or "").strip()
    if planned is True:
        detail_parts: list[str] = []
        for label, key in (
            ("分析目的", "purpose"),
            ("实施时间", "timing"),
            ("信息分数", "information_fraction"),
            ("统计边界", "statistical_boundary"),
            ("α控制", "alpha_control"),
            ("独立委员会", "independent_committee"),
            ("操作防火墙", "operational_firewall"),
        ):
            value = str(interim.get(key) or "").strip()
            if value:
                detail_parts.append(f"{label}：{value}")
        notes = str(interim.get("notes") or "").strip()
        if notes:
            detail_parts.append(notes)
        if detail_parts:
            return "；".join(detail_parts)
        return statistical_text or "计划期中分析（具体统计细节待确认）。"
    # planned is None (undecided) — fall back to legacy text only.
    return statistical_text


def _required_text(value: str, label: str) -> str:
    canonical = value.strip()
    if not canonical:
        raise ValueError(f"{label} must not be blank")
    return canonical


def _canonical_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize path_overrides for stable hashing: sorted by key."""
    return {k: overrides[k] for k in sorted(overrides.keys())}


def _build_edited_evidence_refs(
    *,
    candidate: AuthoringPrefillCandidate,
    applied_candidate_paths: list[str],
) -> list[AuthoringPrefillEvidenceRef]:
    """Build deduplicated evidence refs for a user-edited composite.

    Only refs corresponding to non-override path bindings are included,
    one ref per unique catalog entry_id. This prevents duplication when
    multiple paths share the same source entry.
    """
    applied_set = set(applied_candidate_paths)
    seen_entry_ids: set[str] = set()
    refs: list[AuthoringPrefillEvidenceRef] = []

    # Map catalog_entry_id -> evidence_ref from the original candidate.
    entry_to_ref: dict[str, AuthoringPrefillEvidenceRef] = {}
    for binding in candidate.claim_bindings:
        if binding.target_path not in applied_set:
            continue
        if binding.catalog_entry_id in seen_entry_ids:
            continue
        seen_entry_ids.add(binding.catalog_entry_id)
        # Find the matching evidence_ref from the original candidate.
        for ref in candidate.evidence_refs:
            if (
                ref.source_id == binding.source_id
                and ref.locator == binding.locator
            ):
                entry_to_ref[binding.catalog_entry_id] = ref
                break

    # If no matching ref found from candidate, build one from binding data.
    for binding in candidate.claim_bindings:
        if binding.target_path not in applied_set:
            continue
        if binding.catalog_entry_id in entry_to_ref:
            refs.append(entry_to_ref[binding.catalog_entry_id])
        else:
            refs.append(
                AuthoringPrefillEvidenceRef(
                    source_kind="study_definition",
                    source_id=binding.source_id,
                    locator=binding.locator,
                    quote_sha256=binding.quote_sha256,
                )
            )

    return refs
