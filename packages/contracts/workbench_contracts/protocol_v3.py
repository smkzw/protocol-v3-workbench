"""Canonical Protocol v3 contracts.

This module is deliberately isolated from the legacy medical-writing models.  It
contains immutable value contracts only; repositories, reducers and API
adapters are introduced by later migration tasks.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Annotated, ClassVar, Literal, Optional, Union

from typing_extensions import Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)


PROTOCOL_V3_SCHEMA_VERSION = "mw_protocol_v3_contract_v1"


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return value


StableId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
AwareDateTime = Annotated[datetime, AfterValidator(_require_aware_datetime)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveRevision = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class CanonicalState(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    FROZEN = "frozen"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"


_CANONICAL_STATE_TRANSITIONS: dict[CanonicalState, frozenset[CanonicalState]] = {
    CanonicalState.RAW: frozenset(
        {CanonicalState.NORMALIZED, CanonicalState.QUARANTINED}
    ),
    CanonicalState.NORMALIZED: frozenset(
        {CanonicalState.PROPOSED, CanonicalState.QUARANTINED}
    ),
    CanonicalState.PROPOSED: frozenset(
        {
            CanonicalState.CONFIRMED,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }
    ),
    CanonicalState.CONFIRMED: frozenset(
        {
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }
    ),
    CanonicalState.FROZEN: frozenset(
        {CanonicalState.SUPERSEDED, CanonicalState.QUARANTINED}
    ),
    CanonicalState.SUPERSEDED: frozenset(),
    CanonicalState.QUARANTINED: frozenset(),
}


def assert_canonical_state_transition(
    current: Union[CanonicalState, str],
    target: Union[CanonicalState, str],
) -> CanonicalState:
    """Return the target state when the lifecycle edge is legal.

    Same-state writes are intentionally not transitions.  Callers that want an
    idempotent no-op should compare the current state before invoking a reducer.
    """

    current_state = CanonicalState(current)
    target_state = CanonicalState(target)
    if target_state not in _CANONICAL_STATE_TRANSITIONS[current_state]:
        raise ValueError(
            f"illegal canonical state transition: {current_state.value} -> "
            f"{target_state.value}"
        )
    return target_state


def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicate IDs")
    return values


def _strip_material_metadata(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _strip_material_metadata(item)
            for key, item in value.items()
            if key not in ProtocolV3Model.material_metadata_fields
        }
    if isinstance(value, list):
        return [_strip_material_metadata(item) for item in value]
    return value


class ProtocolV3Model(BaseModel):
    """Strict immutable base with stable material hashing."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    schema_version: Literal["mw_protocol_v3_contract_v1"] = (
        PROTOCOL_V3_SCHEMA_VERSION
    )

    material_metadata_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "canonical_state",
            "created_at",
            "decided_at",
            "display_progress",
            "emitted_at",
            "expected_state_revision",
            "journey_counter",
            "previous_revision_sha256",
            "revision",
            "state_revision",
            "updated_at",
        }
    )

    def material_payload(self) -> dict[str, JsonValue]:
        dumped = self.model_dump(mode="json")
        material = _strip_material_metadata(dumped)
        assert isinstance(material, dict)
        return material

    def material_sha256(self) -> str:
        payload = json.dumps(
            self.material_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(payload).hexdigest()


class StatefulProtocolV3Model(ProtocolV3Model):
    canonical_state: CanonicalState


class EvidenceClass(str, Enum):
    PROJECT_PRIMARY = "project_primary"
    REGULATORY_OR_GUIDELINE = "regulatory_or_guideline"
    COMPETITOR_FULL_PROTOCOL = "competitor_full_protocol"
    REGISTRY_ONLY = "registry_only"
    PEER_REVIEWED = "peer_reviewed"
    COMPANY_STYLE_ONLY = "company_style_only"
    NONE = "none"


class SourceRole(str, Enum):
    PROJECT_PRIMARY = "project_primary"
    REGULATORY_OR_GUIDELINE = "regulatory_or_guideline"
    COMPETITOR_FULL_PROTOCOL = "competitor_full_protocol"
    REGISTRY_ONLY = "registry_only"
    PEER_REVIEWED = "peer_reviewed"
    COMPANY_STYLE_ONLY = "company_style_only"
    ENDPOINT_OR_INSTRUMENT = "endpoint_or_instrument"


class SourceCategory(str, Enum):
    PROJECT_OR_INVESTIGATOR_BROCHURE = "project_or_investigator_brochure"
    REGULATORY = "regulatory"
    GUIDELINE_OR_CONSENSUS = "guideline_or_consensus"
    TRIAL_REGISTRY = "trial_registry"
    COMPETITOR_PROTOCOL = "competitor_protocol"
    ENDPOINT_OR_INSTRUMENT = "endpoint_or_instrument"
    PEER_REVIEWED = "peer_reviewed"
    COMPANY_TEMPLATE_OR_CORPUS = "company_template_or_corpus"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONFLICTS = "conflicts"
    LIMITS = "limits"


class LocatorKind(str, Enum):
    BODY = "body"
    TABLE = "table"
    FIGURE = "figure"
    PAGE = "page"


class ApplicabilityStatus(str, Enum):
    APPLICABLE = "applicable"
    CONDITIONAL = "conditional"
    NOT_APPLICABLE = "not_applicable"


class StructuralObjectKind(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    SCHEDULE_OF_ACTIVITIES = "schedule_of_activities"
    FIGURE = "figure"
    FORMULA = "formula"
    INSTRUMENT = "instrument"


class SemanticBlockKind(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    SCHEDULE_OF_ACTIVITIES = "schedule_of_activities"
    FIGURE = "figure"
    FORMULA = "formula"
    INSTRUMENT = "instrument"
    PAGE_FIELD = "page_field"


class ActorType(str, Enum):
    AI = "ai"
    USER = "user"
    SYSTEM = "system"


class ResearchSeed(StatefulProtocolV3Model):
    research_seed_id: StableId
    research_drug_raw: NonEmptyText
    dosage_form_and_route_raw: NonEmptyText
    anticipated_dose_raw: NonEmptyText
    target_or_mechanism_raw: NonEmptyText
    indication_raw: NonEmptyText
    clinical_phase_raw: NonEmptyText
    populations_raw: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    comparator_raw: NonEmptyText
    created_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.RAW

    @model_validator(mode="after")
    def validate_seed_state_and_populations(self) -> Self:
        if self.canonical_state not in {
            CanonicalState.RAW,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("ResearchSeed must remain raw or quarantined")
        _unique(self.populations_raw, "populations_raw")
        return self


class NormalizedResearchSeed(StatefulProtocolV3Model):
    normalized_seed_id: StableId
    research_seed_id: StableId
    research_seed_sha256: Sha256
    research_drug: NonEmptyText
    dosage_form_and_route: NonEmptyText
    anticipated_dose: NonEmptyText
    target_or_mechanism: NonEmptyText
    indication: NonEmptyText
    clinical_phase: NonEmptyText
    populations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    comparator: NonEmptyText
    normalization_notes: tuple[NonEmptyText, ...] = ()
    updated_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.NORMALIZED

    @model_validator(mode="after")
    def validate_normalized_seed(self) -> Self:
        if self.canonical_state not in {
            CanonicalState.NORMALIZED,
            CanonicalState.PROPOSED,
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("NormalizedResearchSeed cannot return to raw")
        _unique(self.populations, "populations")
        return self


class SourceAcquisitionPlan(StatefulProtocolV3Model):
    source_acquisition_plan_id: StableId
    normalized_seed_id: StableId
    normalized_seed_sha256: Sha256
    source_categories: Annotated[tuple[SourceCategory, ...], Field(min_length=1)]
    registries_and_sites: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    query_families: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    synonyms: tuple[NonEmptyText, ...] = ()
    jurisdiction: NonEmptyText
    search_start_date: Optional[date] = None
    search_end_date: date
    inclusion_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    exclusion_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    version_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    completeness_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    exceptions: tuple[NonEmptyText, ...] = ()
    required_discovery_denominator: Annotated[int, Field(ge=1)]
    researched_competitor_denominator: NonNegativeInt = 0
    linked_protocol_denominator: NonNegativeInt = 0
    created_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        _unique(tuple(item.value for item in self.source_categories), "source_categories")
        _unique(self.registries_and_sites, "registries_and_sites")
        _unique(self.query_families, "query_families")
        if self.linked_protocol_denominator > self.researched_competitor_denominator:
            raise ValueError(
                "linked_protocol_denominator cannot exceed "
                "researched_competitor_denominator"
            )
        if self.search_start_date and self.search_start_date > self.search_end_date:
            raise ValueError("search date range is reversed")
        if self.canonical_state not in {
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("SourceAcquisitionPlan must be confirmed before use")
        return self


class ArtifactDerivationKind(str, Enum):
    ORIGINAL = "original"
    OCR = "ocr"
    TRANSLATION = "translation"
    STRUCTURED_EXTRACTION = "structured_extraction"


class SourceArtifact(StatefulProtocolV3Model):
    source_artifact_id: StableId
    logical_source_key: NonEmptyText
    content_sha256: Sha256
    source_role: SourceRole
    source_version: NonEmptyText
    jurisdiction: NonEmptyText
    mime_type: NonEmptyText
    derivation_kind: ArtifactDerivationKind = ArtifactDerivationKind.ORIGINAL
    parent_artifact_id: Optional[StableId] = None
    parent_content_sha256: Optional[Sha256] = None
    effective_at: Optional[AwareDateTime] = None
    captured_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.CONFIRMED

    @model_validator(mode="after")
    def validate_artifact_identity(self) -> Self:
        is_derived = self.derivation_kind is not ArtifactDerivationKind.ORIGINAL
        has_parent_id = self.parent_artifact_id is not None
        has_parent_hash = self.parent_content_sha256 is not None
        if has_parent_id != has_parent_hash:
            raise ValueError("parent artifact identity must include both ID and hash")
        has_parent_identity = has_parent_id and has_parent_hash
        if is_derived and not has_parent_identity:
            raise ValueError(
                "derived artifacts require complete parent artifact identity"
            )
        if not is_derived and has_parent_identity:
            raise ValueError("original artifacts must not declare parent identity")
        if self.canonical_state not in {
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("SourceArtifact requires confirmed identity")
        return self


class EvidenceUnit(StatefulProtocolV3Model):
    evidence_unit_id: StableId
    source_artifact_id: StableId
    source_content_sha256: Sha256
    source_role: SourceRole
    locator_kind: LocatorKind
    locator: NonEmptyText
    context_before: str = ""
    body: NonEmptyText
    context_after: str = ""
    quality_score: UnitInterval
    extracted_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.CONFIRMED


class MedicalAdmissionUnit(StatefulProtocolV3Model):
    medical_admission_unit_id: StableId
    evidence_unit_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    claim_type: NonEmptyText
    fact_paths: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    source_roles: Annotated[tuple[SourceRole, ...], Field(min_length=1)]
    relation: EvidenceRelation
    locator_kind: Literal[LocatorKind.BODY, LocatorKind.TABLE, LocatorKind.FIGURE]
    locator: NonEmptyText
    context_window: NonEmptyText
    quality_score: UnitInterval
    semantic_node_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    chapter_contract_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    source_content_sha256: Sha256
    admitted_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.CONFIRMED

    @model_validator(mode="after")
    def validate_admission_unit(self) -> Self:
        _unique(self.evidence_unit_ids, "evidence_unit_ids")
        _unique(self.fact_paths, "fact_paths")
        _unique(tuple(item.value for item in self.source_roles), "source_roles")
        _unique(self.semantic_node_ids, "semantic_node_ids")
        _unique(self.chapter_contract_ids, "chapter_contract_ids")
        return self


class ClaimEvidenceLink(StatefulProtocolV3Model):
    claim_evidence_link_id: StableId
    claim_id: StableId
    evidence_unit_ids: tuple[StableId, ...] = ()
    medical_admission_unit_ids: tuple[StableId, ...] = ()
    relation: EvidenceRelation
    rationale: NonEmptyText
    canonical_state: CanonicalState = CanonicalState.CONFIRMED

    @model_validator(mode="after")
    def validate_link(self) -> Self:
        _unique(self.evidence_unit_ids, "evidence_unit_ids")
        _unique(self.medical_admission_unit_ids, "medical_admission_unit_ids")
        if not self.evidence_unit_ids and not self.medical_admission_unit_ids:
            raise ValueError("a claim must link to evidence or an admission unit")
        return self


class RecommendationOption(StatefulProtocolV3Model):
    recommendation_option_id: StableId
    decision_key: StableId
    label: NonEmptyText
    rationale: NonEmptyText
    evidence_class: EvidenceClass
    claim_evidence_link_ids: tuple[StableId, ...] = ()
    uncertainty: NonEmptyText
    downstream_impact: NonEmptyText
    is_default: bool = False
    canonical_state: CanonicalState = CanonicalState.PROPOSED

    @field_validator("claim_evidence_link_ids")
    @classmethod
    def unique_links(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "claim_evidence_link_ids")


class DecisionRecord(StatefulProtocolV3Model):
    decision_record_id: StableId
    decision_key: StableId
    snapshot_sha256: Sha256
    expected_state_revision: NonNegativeInt
    state_revision: PositiveRevision
    option_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    selected_option_id: StableId
    actor_type: ActorType
    actor_id: StableId
    reason: NonEmptyText
    decided_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.CONFIRMED

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        _unique(self.option_ids, "option_ids")
        if self.selected_option_id not in self.option_ids:
            raise ValueError("selected_option_id must be one of option_ids")
        if self.state_revision != self.expected_state_revision + 1:
            raise ValueError("state_revision must advance the expected CAS revision once")
        if self.canonical_state not in {
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("DecisionRecord must capture a resolved decision")
        return self


class StudyDefinitionV3(StatefulProtocolV3Model):
    study_definition_id: StableId
    project_id: StableId
    revision: PositiveRevision
    previous_revision_sha256: Optional[Sha256] = None
    normalized_seed_id: StableId
    normalized_seed_sha256: Sha256
    facts: Annotated[dict[NonEmptyText, JsonValue], Field(min_length=1)]
    decision_record_ids: tuple[StableId, ...] = ()
    updated_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.PROPOSED

    @model_validator(mode="after")
    def validate_study_definition(self) -> Self:
        _unique(self.decision_record_ids, "decision_record_ids")
        if (self.revision == 1) != (self.previous_revision_sha256 is None):
            raise ValueError(
                "revision 1 must not declare a predecessor; later revisions require one"
            )
        if self.canonical_state not in {
            CanonicalState.PROPOSED,
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("StudyDefinitionV3 cannot be raw or merely normalized")
        return self


class ApplicabilityEntry(ProtocolV3Model):
    applicability_entry_id: StableId
    semantic_node_id: StableId
    status: ApplicabilityStatus
    reason: NonEmptyText
    triggering_fact_paths: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    rule_id: StableId

    @field_validator("triggering_fact_paths")
    @classmethod
    def unique_fact_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "triggering_fact_paths")


class ApplicabilitySnapshot(StatefulProtocolV3Model):
    applicability_snapshot_id: StableId
    study_definition_id: StableId
    study_definition_sha256: Sha256
    ruleset_id: StableId
    ruleset_version: NonEmptyText
    ruleset_sha256: Sha256
    entries: Annotated[tuple[ApplicabilityEntry, ...], Field(min_length=1)]
    created_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        _unique(
            tuple(item.applicability_entry_id for item in self.entries),
            "applicability_entry_ids",
        )
        _unique(
            tuple(item.semantic_node_id for item in self.entries),
            "semantic_node_ids",
        )
        return self


class ChapterContract(StatefulProtocolV3Model):
    chapter_contract_id: StableId
    semantic_node_id: StableId
    contract_version: NonEmptyText
    template_id: StableId
    template_sha256: Sha256
    chapter_skill_id: StableId
    chapter_skill_version: NonEmptyText
    required_fact_paths: tuple[NonEmptyText, ...] = ()
    required_admission_claim_types: tuple[NonEmptyText, ...] = ()
    required_source_roles: tuple[SourceRole, ...] = ()
    required_claim_types: tuple[NonEmptyText, ...] = ()
    required_structural_objects: tuple[StructuralObjectKind, ...] = ()
    positive_qc_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    word_block_schema: NonEmptyText
    dependency_ids: tuple[StableId, ...] = ()
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_non_vacuous_contract(self) -> Self:
        _unique(self.required_fact_paths, "required_fact_paths")
        _unique(self.required_admission_claim_types, "required_admission_claim_types")
        _unique(
            tuple(item.value for item in self.required_source_roles),
            "required_source_roles",
        )
        _unique(self.required_claim_types, "required_claim_types")
        _unique(
            tuple(item.value for item in self.required_structural_objects),
            "required_structural_objects",
        )
        _unique(self.dependency_ids, "dependency_ids")
        obligations = (
            self.required_fact_paths,
            self.required_admission_claim_types,
            self.required_source_roles,
            self.required_claim_types,
            self.required_structural_objects,
        )
        if not any(obligations):
            raise ValueError("ChapterContract is vacuous")
        if self.canonical_state not in {
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("ChapterContract must be frozen before execution")
        return self


class SubstantiveContentContract(StatefulProtocolV3Model):
    substantive_content_contract_id: StableId
    chapter_contract_id: StableId
    required_claim_types: tuple[NonEmptyText, ...] = ()
    required_fact_paths: tuple[NonEmptyText, ...] = ()
    minimum_source_roles: tuple[SourceRole, ...] = ()
    required_admission_claim_types: tuple[NonEmptyText, ...] = ()
    project_specific_elements: tuple[NonEmptyText, ...] = ()
    required_structural_objects: tuple[StructuralObjectKind, ...] = ()
    required_object_cells: tuple[NonEmptyText, ...] = ()
    skeleton_risk_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_substantive_obligations(self) -> Self:
        collections = (
            self.required_claim_types,
            self.required_fact_paths,
            tuple(item.value for item in self.minimum_source_roles),
            self.required_admission_claim_types,
            self.project_specific_elements,
            tuple(item.value for item in self.required_structural_objects),
            self.required_object_cells,
        )
        for index, values in enumerate(collections):
            _unique(values, f"substantive_obligation_{index}")
        if not any(collections):
            raise ValueError("SubstantiveContentContract is vacuous")
        return self


class SemanticBlock(StatefulProtocolV3Model):
    semantic_block_id: StableId
    semantic_node_id: StableId
    chapter_contract_id: StableId
    substantive_content_contract_id: StableId
    block_kind: SemanticBlockKind
    content: NonEmptyText
    fact_paths: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    claim_evidence_link_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    medical_admission_unit_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    content_sha256: Sha256
    canonical_state: CanonicalState = CanonicalState.CONFIRMED

    @model_validator(mode="after")
    def validate_block_bindings(self) -> Self:
        _unique(self.fact_paths, "fact_paths")
        _unique(self.claim_evidence_link_ids, "claim_evidence_link_ids")
        _unique(self.medical_admission_unit_ids, "medical_admission_unit_ids")
        return self


class SemanticDocumentRevision(StatefulProtocolV3Model):
    semantic_document_revision_id: StableId
    project_id: StableId
    revision: PositiveRevision
    previous_revision_sha256: Optional[Sha256] = None
    study_definition_id: StableId
    study_definition_sha256: Sha256
    applicability_snapshot_id: StableId
    applicability_snapshot_sha256: Sha256
    semantic_blocks: Annotated[tuple[SemanticBlock, ...], Field(min_length=1)]
    chapter_contract_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    updated_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.PROPOSED

    @model_validator(mode="after")
    def validate_document_revision(self) -> Self:
        if (self.revision == 1) != (self.previous_revision_sha256 is None):
            raise ValueError(
                "revision 1 must not declare a predecessor; later revisions require one"
            )
        _unique(
            tuple(block.semantic_block_id for block in self.semantic_blocks),
            "semantic_block_ids",
        )
        _unique(self.chapter_contract_hashes, "chapter_contract_hashes")
        return self


class ChapterLockSnapshot(StatefulProtocolV3Model):
    chapter_lock_snapshot_id: StableId
    semantic_node_id: StableId
    semantic_document_revision_id: StableId
    semantic_document_sha256: Sha256
    upstream_artifact_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    accepted_semantic_block_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    locked_by_actor_id: StableId
    locked_at: AwareDateTime
    is_locked: bool = True
    auto_unlock_reason: Optional[NonEmptyText] = None
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
        _unique(self.upstream_artifact_hashes, "upstream_artifact_hashes")
        _unique(self.accepted_semantic_block_hashes, "accepted_semantic_block_hashes")
        if self.is_locked == (self.auto_unlock_reason is not None):
            raise ValueError(
                "locked snapshots must not have an unlock reason; unlocked snapshots require one"
            )
        return self


class SideEffectKind(str, Enum):
    NONE = "none"
    CANONICAL_PROPOSAL = "canonical_proposal"
    ARTIFACT_CREATE = "artifact_create"
    EXTERNAL_FETCH = "external_fetch"
    EXPORT = "export"


class SkillDefinition(StatefulProtocolV3Model):
    skill_definition_id: StableId
    skill_version: NonEmptyText
    agent_role: Literal[
        "coordinator",
        "corpus",
        "design_and_summary",
        "full_draft",
        "quality_control",
    ]
    input_schema_ref: NonEmptyText
    output_schema_ref: NonEmptyText
    evidence_requirements: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    allowed_tools: tuple[NonEmptyText, ...] = ()
    allowed_paths: tuple[NonEmptyText, ...] = ()
    side_effect_kind: SideEffectKind = SideEffectKind.NONE
    acceptance_test_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_skill(self) -> Self:
        _unique(self.allowed_tools, "allowed_tools")
        _unique(self.allowed_paths, "allowed_paths")
        _unique(self.acceptance_test_ids, "acceptance_test_ids")
        return self


class SensitivityTier(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ReasoningEffort(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"
    XHIGH = "xhigh"


class NodeExecutionContract(StatefulProtocolV3Model):
    node_execution_contract_id: StableId
    skill_definition_id: StableId
    role: NonEmptyText
    harness: NonEmptyText
    provider: NonEmptyText
    model: NonEmptyText
    reasoning_effort: ReasoningEffort
    provider_session_id: Optional[NonEmptyText] = None
    same_session_recovery: bool
    timeout_seconds: Annotated[int, Field(gt=0)]
    fallback_policy_id: StableId
    prompt_sha256: Sha256
    input_schema_ref: NonEmptyText
    output_schema_ref: NonEmptyText
    allowed_tools: tuple[NonEmptyText, ...] = ()
    allowed_paths: tuple[NonEmptyText, ...] = ()
    permission_policy_id: StableId
    input_artifact_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    sensitivity_tier: SensitivityTier
    allowed_providers: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    allowed_regions: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    redaction_policy_id: StableId
    retention_policy_id: StableId
    logical_call_id: StableId
    idempotency_key: NonEmptyText
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_execution_contract(self) -> Self:
        _unique(self.allowed_tools, "allowed_tools")
        _unique(self.allowed_paths, "allowed_paths")
        _unique(self.input_artifact_hashes, "input_artifact_hashes")
        _unique(self.allowed_providers, "allowed_providers")
        _unique(self.allowed_regions, "allowed_regions")
        if self.provider not in self.allowed_providers:
            raise ValueError("selected provider is outside the contract allowlist")
        return self


class ReservationStatus(str, Enum):
    RESERVED = "reserved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ExecutionTerminalState(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ExecutionReservation(ProtocolV3Model):
    execution_reservation_id: StableId
    node_execution_contract_id: StableId
    logical_call_id: StableId
    idempotency_key: NonEmptyText
    input_sha256: Sha256
    attempt: PositiveRevision
    transport_attempts: NonNegativeInt = 0
    provider_session_id: Optional[NonEmptyText] = None
    status: ReservationStatus = ReservationStatus.RESERVED
    terminal_state: Optional[ExecutionTerminalState] = None
    output_sha256: Optional[Sha256] = None
    error_code: Optional[StableId] = None
    reserved_at: AwareDateTime
    updated_at: AwareDateTime

    @model_validator(mode="after")
    def validate_reservation_terminal_state(self) -> Self:
        terminal_statuses = {
            ReservationStatus.COMPLETED,
            ReservationStatus.FAILED,
            ReservationStatus.UNKNOWN_OUTCOME,
        }
        if self.status in terminal_statuses:
            if self.terminal_state is None or self.terminal_state.value != self.status.value:
                raise ValueError("terminal_state must match terminal reservation status")
            if self.provider_session_id is None:
                raise ValueError("terminal reservations require provider_session_id")
        elif self.terminal_state is not None:
            raise ValueError("non-terminal reservations must not declare terminal_state")
        if self.status is ReservationStatus.COMPLETED:
            if self.output_sha256 is None or self.error_code is not None:
                raise ValueError("completed reservations require output and no error")
        elif self.status in {
            ReservationStatus.FAILED,
            ReservationStatus.UNKNOWN_OUTCOME,
        }:
            if self.error_code is None or self.output_sha256 is not None:
                raise ValueError("failed/unknown reservations require an error and no output")
        elif self.output_sha256 is not None or self.error_code is not None:
            raise ValueError("non-terminal reservations cannot contain terminal results")
        return self


class WorkflowRunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class WorkflowRun(ProtocolV3Model):
    workflow_run_id: StableId
    graph_version: NonEmptyText
    graph_sha256: Sha256
    contract_schema_version: NonEmptyText
    template_version: NonEmptyText
    template_sha256: Sha256
    skill_definition_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    skill_definition_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    source_revision_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    study_definition_id: StableId
    study_definition_sha256: Sha256
    status: WorkflowRunStatus
    display_progress: UnitInterval = 0.0
    journey_counter: NonNegativeInt = 0
    created_at: AwareDateTime
    updated_at: AwareDateTime

    @model_validator(mode="after")
    def validate_workflow_identity(self) -> Self:
        _unique(self.skill_definition_ids, "skill_definition_ids")
        _unique(self.skill_definition_hashes, "skill_definition_hashes")
        _unique(self.source_revision_hashes, "source_revision_hashes")
        if len(self.skill_definition_ids) != len(self.skill_definition_hashes):
            raise ValueError("skill IDs and hashes must have equal cardinality")
        return self


class DomainEvent(ProtocolV3Model):
    domain_event_id: StableId
    stream_id: StableId
    sequence: PositiveRevision
    event_type: StableId
    payload_schema_version: NonEmptyText
    upcaster_id: StableId
    actor_type: ActorType
    actor_id: StableId
    action: NonEmptyText
    reason: NonEmptyText
    payload: dict[NonEmptyText, JsonValue]
    payload_sha256: Sha256
    previous_event_sha256: Optional[Sha256] = None
    event_sha256: Sha256
    emitted_at: AwareDateTime

    @model_validator(mode="after")
    def validate_event_chain_identity(self) -> Self:
        if (self.sequence == 1) != (self.previous_event_sha256 is None):
            raise ValueError(
                "the first event has no predecessor; later events require one"
            )
        return self


class ProjectionKind(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    STANDALONE_SYNOPSIS = "standalone_synopsis"


class ProjectionArtifact(StatefulProtocolV3Model):
    projection_artifact_id: StableId
    projection_kind: ProjectionKind
    workflow_run_id: StableId
    study_definition_id: StableId
    study_definition_sha256: Sha256
    semantic_document_revision_id: StableId
    semantic_document_sha256: Sha256
    content_sha256: Sha256
    word_receipt_id: Optional[StableId] = None
    word_receipt_sha256: Optional[Sha256] = None
    created_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_projection_receipt(self) -> Self:
        receipt_identity = (
            self.word_receipt_id is not None,
            self.word_receipt_sha256 is not None,
        )
        if receipt_identity[0] != receipt_identity[1]:
            raise ValueError("Word receipt identity must be complete")
        if self.projection_kind in {ProjectionKind.DOCX, ProjectionKind.PDF} and not all(
            receipt_identity
        ):
            raise ValueError("DOCX/PDF projections require a Word receipt")
        return self


class SubmissionEvidencePackage(StatefulProtocolV3Model):
    submission_evidence_package_id: StableId
    project_id: StableId
    workflow_run_id: StableId
    workflow_run_sha256: Sha256
    study_definition_id: StableId
    study_definition_sha256: Sha256
    semantic_document_revision_id: StableId
    semantic_document_sha256: Sha256
    source_manifest_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    medical_admission_unit_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    applicability_snapshot_id: StableId
    applicability_snapshot_sha256: Sha256
    chapter_contract_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    skill_definition_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    decision_record_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    qc_clean_verdict_sha256: Sha256
    word_receipt_id: StableId
    word_receipt_sha256: Sha256
    projection_artifact_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    model_versions: Annotated[dict[NonEmptyText, NonEmptyText], Field(min_length=1)]
    tool_versions: Annotated[dict[NonEmptyText, NonEmptyText], Field(min_length=1)]
    frozen_at: AwareDateTime
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_submission_closure(self) -> Self:
        _unique(self.source_manifest_hashes, "source_manifest_hashes")
        _unique(self.medical_admission_unit_ids, "medical_admission_unit_ids")
        _unique(self.chapter_contract_hashes, "chapter_contract_hashes")
        _unique(self.skill_definition_hashes, "skill_definition_hashes")
        _unique(self.decision_record_ids, "decision_record_ids")
        _unique(self.projection_artifact_ids, "projection_artifact_ids")
        if self.canonical_state is not CanonicalState.FROZEN:
            raise ValueError("SubmissionEvidencePackage must be frozen")
        return self


__all__ = [
    "PROTOCOL_V3_SCHEMA_VERSION",
    "ActorType",
    "ApplicabilityEntry",
    "ApplicabilitySnapshot",
    "ApplicabilityStatus",
    "ArtifactDerivationKind",
    "CanonicalState",
    "ChapterContract",
    "ChapterLockSnapshot",
    "ClaimEvidenceLink",
    "DecisionRecord",
    "DomainEvent",
    "EvidenceClass",
    "EvidenceRelation",
    "EvidenceUnit",
    "ExecutionReservation",
    "ExecutionTerminalState",
    "LocatorKind",
    "MedicalAdmissionUnit",
    "NodeExecutionContract",
    "NormalizedResearchSeed",
    "ProjectionArtifact",
    "ProjectionKind",
    "ProtocolV3Model",
    "ReasoningEffort",
    "RecommendationOption",
    "ResearchSeed",
    "ReservationStatus",
    "SemanticBlock",
    "SemanticBlockKind",
    "SemanticDocumentRevision",
    "SensitivityTier",
    "SideEffectKind",
    "SkillDefinition",
    "SourceAcquisitionPlan",
    "SourceArtifact",
    "SourceCategory",
    "SourceRole",
    "StructuralObjectKind",
    "StudyDefinitionV3",
    "SubmissionEvidencePackage",
    "SubstantiveContentContract",
    "WorkflowRun",
    "WorkflowRunStatus",
    "assert_canonical_state_transition",
]
