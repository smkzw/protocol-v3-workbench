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
    model_serializer,
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


class _FrozenJsonDict(dict[str, JsonValue]):
    """JSON mapping that preserves ``dict`` serialization but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("canonical JSON mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


class _FrozenJsonList(list[JsonValue]):
    """JSON list that remains serializer-compatible but rejects mutation."""

    @staticmethod
    def _immutable(*_args, **_kwargs):
        raise TypeError("canonical JSON list is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable

    def __copy__(self):
        return self

    def __deepcopy__(self, _memo):
        return self


def _freeze_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return _FrozenJsonDict(
            {key: _freeze_json_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenJsonList(_freeze_json_value(item) for item in value)
    return value


def _material_value(value):
    """Serialize model metadata structurally without stripping domain keys."""

    if isinstance(value, ProtocolV3Model):
        return {
            name: _material_value(getattr(value, name))
            for name in type(value).model_fields
            if name not in ProtocolV3Model.material_metadata_fields
            and not (
                isinstance(value, DependencyBoundModel)
                and name == (
                    "dependency_sha256"
                    if value.schema_version == PROTOCOL_V3_SCHEMA_VERSION
                    else value.dependency_field
                )
            )
        }
    if isinstance(value, dict):
        return {key: _material_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_material_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class ProtocolV3Model(BaseModel):
    """Strict immutable base with stable material hashing."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    schema_version: Literal["mw_protocol_v3_contract_v1"] = PROTOCOL_V3_SCHEMA_VERSION

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
        material = _material_value(self)
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


class DependencyBoundModel(StatefulProtocolV3Model):
    """Explicit minor-version compaction; legacy payloads and hashes stay intact."""

    schema_version: Literal["mw_protocol_v3_contract_v1", "mw_protocol_v3_contract_v1_1"] = PROTOCOL_V3_SCHEMA_VERSION
    dependency_field: ClassVar[str]
    dependency_sha256: Optional[Sha256] = None

    def _dependency_hash(self, hashes: tuple[str, ...]) -> str:
        payload = json.dumps(
            {"domain": "mw_protocol_v3_dependencies_v1", "field": self.dependency_field, "hashes": hashes},
            sort_keys=True, separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def validate_dependency_binding(self) -> Self:
        hashes = getattr(self, self.dependency_field)
        _unique(hashes, self.dependency_field)
        if self.schema_version == PROTOCOL_V3_SCHEMA_VERSION:
            if not hashes or self.dependency_sha256 is not None:
                raise ValueError("legacy contracts require dependency hashes and no compact digest")
        else:
            if self.dependency_sha256 is None:
                raise ValueError("compact contracts require a dependency digest")
            if hashes and self._dependency_hash(hashes) != self.dependency_sha256:
                raise ValueError("dependency hashes do not match compact digest")
            object.__setattr__(self, self.dependency_field, ())
        return self

    @model_serializer(mode="wrap")
    def serialize_dependency_binding(self, handler):
        payload = handler(self)
        payload.pop(
            "dependency_sha256" if self.schema_version == PROTOCOL_V3_SCHEMA_VERSION
            else self.dependency_field, None,
        )
        return payload

    def compact_dependencies(self) -> Self:
        if self.schema_version != PROTOCOL_V3_SCHEMA_VERSION:
            return self
        payload = self.model_dump()
        payload.update(
            schema_version="mw_protocol_v3_contract_v1_1",
            dependency_sha256=self._dependency_hash(getattr(self, self.dependency_field)),
        )
        return type(self).model_validate(payload)

    def matches_dependencies(self, hashes: tuple[str, ...]) -> bool:
        if self.schema_version == PROTOCOL_V3_SCHEMA_VERSION:
            return hashes == getattr(self, self.dependency_field)
        return self._dependency_hash(hashes) == self.dependency_sha256


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
        _unique(
            tuple(item.value for item in self.source_categories), "source_categories"
        )
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
            raise ValueError(
                "state_revision must advance the expected CAS revision once"
            )
        if self.canonical_state not in {
            CanonicalState.CONFIRMED,
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("DecisionRecord must capture a resolved decision")
        return self


class StudyDefinitionV3(StatefulProtocolV3Model):
    # Typed fact payloads are exact data, not labels. StableId/NonEmptyText
    # keep their own explicit normalization; inherited JSON text trimming must
    # not rewrite paragraph/table values while reopening a study.
    model_config = ConfigDict(str_strip_whitespace=False)

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
        object.__setattr__(self, "facts", _freeze_json_value(self.facts))
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


class SemanticDocumentRevision(DependencyBoundModel):
    dependency_field: ClassVar[str] = "chapter_contract_hashes"
    semantic_document_revision_id: StableId
    project_id: StableId
    revision: PositiveRevision
    previous_revision_sha256: Optional[Sha256] = None
    study_definition_id: StableId
    study_definition_sha256: Sha256
    applicability_snapshot_id: StableId
    applicability_snapshot_sha256: Sha256
    semantic_blocks: Annotated[tuple[SemanticBlock, ...], Field(min_length=1)]
    chapter_contract_hashes: tuple[Sha256, ...] = ()
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
        return self


class ChapterLockSnapshot(DependencyBoundModel):
    dependency_field: ClassVar[str] = "upstream_artifact_hashes"
    chapter_lock_snapshot_id: StableId
    semantic_node_id: StableId
    semantic_document_revision_id: StableId
    semantic_document_sha256: Sha256
    upstream_artifact_hashes: tuple[Sha256, ...] = ()
    accepted_semantic_block_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    locked_by_actor_id: StableId
    locked_at: AwareDateTime
    is_locked: bool = True
    auto_unlock_reason: Optional[NonEmptyText] = None
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
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


class NodeExecutionContract(DependencyBoundModel):
    dependency_field: ClassVar[str] = "input_artifact_hashes"
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
    input_artifact_hashes: tuple[Sha256, ...] = ()
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
            if (
                self.terminal_state is None
                or self.terminal_state.value != self.status.value
            ):
                raise ValueError(
                    "terminal_state must match terminal reservation status"
                )
            if self.provider_session_id is None:
                raise ValueError("terminal reservations require provider_session_id")
        elif self.terminal_state is not None:
            raise ValueError(
                "non-terminal reservations must not declare terminal_state"
            )
        if self.status is ReservationStatus.COMPLETED:
            if self.output_sha256 is None or self.error_code is not None:
                raise ValueError("completed reservations require output and no error")
        elif self.status in {
            ReservationStatus.FAILED,
            ReservationStatus.UNKNOWN_OUTCOME,
        }:
            if self.error_code is None or self.output_sha256 is not None:
                raise ValueError(
                    "failed/unknown reservations require an error and no output"
                )
        elif self.output_sha256 is not None or self.error_code is not None:
            raise ValueError(
                "non-terminal reservations cannot contain terminal results"
            )
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
    migrated_payload_sha256: Optional[Sha256] = None
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
        if self.projection_kind in {
            ProjectionKind.DOCX,
            ProjectionKind.PDF,
        } and not all(receipt_identity):
            raise ValueError("DOCX/PDF projections require a Word receipt")
        return self


class SubmissionEvidencePackage(DependencyBoundModel):
    dependency_field: ClassVar[str] = "chapter_contract_hashes"
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
    chapter_contract_hashes: tuple[Sha256, ...] = ()
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
        _unique(self.skill_definition_hashes, "skill_definition_hashes")
        _unique(self.decision_record_ids, "decision_record_ids")
        _unique(self.projection_artifact_ids, "projection_artifact_ids")
        if self.canonical_state is not CanonicalState.FROZEN:
            raise ValueError("SubmissionEvidencePackage must be frozen")
        return self


# ---------------------------------------------------------------------------
# Chapter contract v2 (Task3R.2).  Explicitly versioned additive extension:
# the v1 classes above keep their serialized bytes and material hashes, and
# these typed value contracts never add serialized defaults to v1 models.
# ---------------------------------------------------------------------------

CHAPTER_CONTRACT_V2_SCHEMA_VERSION = "mw_protocol_v3_contract_v2"


class FactObligation(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class ClaimObligation(str, Enum):
    REQUIRED = "required"
    ALLOWED = "allowed"
    QUALIFIED = "qualified"
    FORBIDDEN = "forbidden"


class PatientParticipationStatus(str, Enum):
    PARTICIPATED = "participated"
    NON_PARTICIPATION_WITH_REASON = "non_participation_with_reason"


class FactRequirement(ProtocolV3Model):
    fact_path: NonEmptyText
    obligation: FactObligation
    rationale: NonEmptyText


class ClaimRequirement(ProtocolV3Model):
    claim_type: NonEmptyText
    obligation: ClaimObligation
    rationale: NonEmptyText
    qualifying_conditions: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_qualified_claim(self) -> Self:
        _unique(self.qualifying_conditions, "qualifying_conditions")
        if (
            self.obligation is ClaimObligation.QUALIFIED
            and not self.qualifying_conditions
        ):
            raise ValueError("qualified claims require qualifying conditions")
        return self


class EvidenceSourceRequirement(ProtocolV3Model):
    """Source-role, admission-type and locator/context floor for chapter evidence."""

    source_roles: Annotated[tuple[SourceRole, ...], Field(min_length=1)]
    admission_claim_types: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    allowed_locator_kinds: Annotated[tuple[LocatorKind, ...], Field(min_length=1)]
    require_context_window: bool
    minimum_quality_score: UnitInterval

    @model_validator(mode="after")
    def validate_evidence_requirement(self) -> Self:
        _unique(tuple(item.value for item in self.source_roles), "source_roles")
        _unique(self.admission_claim_types, "admission_claim_types")
        chapter_admissible = {LocatorKind.BODY, LocatorKind.TABLE, LocatorKind.FIGURE}
        for kind in self.allowed_locator_kinds:
            if kind not in chapter_admissible:
                raise ValueError(
                    "allowed_locator_kinds must stay chapter-admissible "
                    "(body, table or figure)"
                )
        _unique(
            tuple(item.value for item in self.allowed_locator_kinds),
            "allowed_locator_kinds",
        )
        return self


class StructuralObjectObligation(ProtocolV3Model):
    object_kind: StructuralObjectKind
    minimum_occurrences: Annotated[int, Field(ge=1)]
    project_specific_specification: NonEmptyText
    required_object_cells: tuple[StableId, ...] = ()

    @model_validator(mode="after")
    def validate_object_cells(self) -> Self:
        _unique(self.required_object_cells, "required_object_cells")
        return self


class WordFormattingRules(ProtocolV3Model):
    word_formatting_rules_id: StableId
    required_styles: tuple[NonEmptyText, ...] = ()
    forbidden_styles: tuple[NonEmptyText, ...] = ()
    required_bookmarks: tuple[NonEmptyText, ...] = ()
    required_cross_references: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_word_rules(self) -> Self:
        _unique(self.required_styles, "required_styles")
        _unique(self.forbidden_styles, "forbidden_styles")
        _unique(self.required_bookmarks, "required_bookmarks")
        _unique(self.required_cross_references, "required_cross_references")
        if set(self.required_styles) & set(self.forbidden_styles):
            raise ValueError(
                "conflicting styles: a style cannot be required and forbidden"
            )
        obligations = (
            self.required_styles,
            self.forbidden_styles,
            self.required_bookmarks,
            self.required_cross_references,
        )
        if not any(obligations):
            raise ValueError("word formatting rules are vacuous")
        return self


class ConditionalApplicabilityRule(ProtocolV3Model):
    conditional_applicability_rule_id: StableId
    triggering_fact_paths: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    condition: NonEmptyText
    rationale: NonEmptyText
    required_when_active_fact_paths: tuple[NonEmptyText, ...] = ()
    required_when_active_claim_types: tuple[NonEmptyText, ...] = ()
    required_when_active_source_roles: tuple[SourceRole, ...] = ()
    required_when_active_structural_objects: tuple[StructuralObjectKind, ...] = ()

    @model_validator(mode="after")
    def validate_conditional_rule(self) -> Self:
        _unique(self.triggering_fact_paths, "triggering_fact_paths")
        _unique(
            self.required_when_active_fact_paths,
            "required_when_active_fact_paths",
        )
        _unique(
            self.required_when_active_claim_types,
            "required_when_active_claim_types",
        )
        _unique(
            tuple(item.value for item in self.required_when_active_source_roles),
            "required_when_active_source_roles",
        )
        _unique(
            tuple(
                item.value for item in self.required_when_active_structural_objects
            ),
            "required_when_active_structural_objects",
        )
        when_active = (
            self.required_when_active_fact_paths,
            self.required_when_active_claim_types,
            self.required_when_active_source_roles,
            self.required_when_active_structural_objects,
        )
        if not any(when_active):
            raise ValueError(
                "conditional applicability rule is vacuous without when-active "
                "obligations"
            )
        return self


class RepairStep(ProtocolV3Model):
    repair_step_id: StableId
    sequence: PositiveRevision
    action: NonEmptyText
    owner: ActorType


class DependencyRepairPolicy(ProtocolV3Model):
    """Bounded repair ownership for upstream dependency drift."""

    dependency_repair_policy_id: StableId
    dependency_ids: Annotated[tuple[StableId, ...], Field(min_length=1)]
    downstream_impact: NonEmptyText
    repair_owner: ActorType
    max_repair_attempts: Annotated[int, Field(ge=1, le=5)]
    repair_steps: Annotated[tuple[RepairStep, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_repair_policy(self) -> Self:
        _unique(self.dependency_ids, "dependency_ids")
        _unique(
            tuple(step.repair_step_id for step in self.repair_steps),
            "repair_step_ids",
        )
        _unique(
            tuple(step.sequence for step in self.repair_steps),
            "repair_step_sequences",
        )
        return self


class PositiveQcRule(ProtocolV3Model):
    positive_qc_rule_id: StableId
    rule: NonEmptyText


class CriticalToQualityItem(ProtocolV3Model):
    ctq_item_id: StableId
    question: NonEmptyText
    linked_fact_paths: tuple[NonEmptyText, ...] = ()
    linked_claim_types: tuple[NonEmptyText, ...] = ()
    positive_qc_rule_ids: tuple[StableId, ...] = ()
    risk_if_unmet: NonEmptyText

    @model_validator(mode="after")
    def validate_ctq_anchor(self) -> Self:
        _unique(self.linked_fact_paths, "linked_fact_paths")
        _unique(self.linked_claim_types, "linked_claim_types")
        _unique(self.positive_qc_rule_ids, "positive_qc_rule_ids")
        if not self.linked_fact_paths and not self.linked_claim_types:
            raise ValueError("a CtQ item must anchor to a fact path or claim type")
        return self


class PatientParticipationObligation(ProtocolV3Model):
    """Approved product traceability tied to an existing DecisionRecord.

    This is not a body chapter and not a claim that any ICH section mandates
    documenting non-participation: the recorded reason is AI-prepared for the
    already-approved decision and carries no arbitrary maximum length.
    """

    patient_participation_obligation_id: StableId
    decision_record_id: StableId
    decision_record_sha256: Sha256
    participation_status: PatientParticipationStatus
    ai_prepared_reason: NonEmptyText


class RegistryConsistencyObligation(ProtocolV3Model):
    registry_consistency_obligation_id: StableId
    registry_name: NonEmptyText
    eligibility_fact_paths: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    consistency_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_registry_obligation(self) -> Self:
        _unique(self.eligibility_fact_paths, "eligibility_fact_paths")
        _unique(self.consistency_rules, "consistency_rules")
        return self


class SubstantiveContentContractV2(StatefulProtocolV3Model):
    schema_version: Literal["mw_protocol_v3_contract_v2"] = (
        CHAPTER_CONTRACT_V2_SCHEMA_VERSION
    )
    substantive_content_contract_id: StableId
    chapter_contract_id: StableId
    fact_requirements: tuple[FactRequirement, ...] = ()
    claim_requirements: tuple[ClaimRequirement, ...] = ()
    evidence_source_requirements: tuple[EvidenceSourceRequirement, ...] = ()
    structural_object_obligations: tuple[StructuralObjectObligation, ...] = ()
    project_specific_elements: tuple[NonEmptyText, ...] = ()
    skeleton_risk_rules: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_substantive_obligations_v2(self) -> Self:
        fact_paths = tuple(item.fact_path for item in self.fact_requirements)
        if len(fact_paths) != len(set(fact_paths)):
            raise ValueError(
                "conflicting fact obligations: a fact path cannot carry two "
                "obligation entries"
            )
        claim_types = tuple(item.claim_type for item in self.claim_requirements)
        if len(claim_types) != len(set(claim_types)):
            raise ValueError(
                "conflicting claim obligations: a claim type cannot carry two "
                "obligation entries"
            )
        _unique(self.project_specific_elements, "project_specific_elements")
        _unique(
            tuple(
                item.object_kind.value for item in self.structural_object_obligations
            ),
            "structural_object_obligations",
        )
        forbidden_claims = {
            item.claim_type
            for item in self.claim_requirements
            if item.obligation is ClaimObligation.FORBIDDEN
        }
        for evidence in self.evidence_source_requirements:
            if forbidden_claims & set(evidence.admission_claim_types):
                raise ValueError(
                    "a forbidden claim type cannot be an admission requirement"
                )
        obligations = (
            self.fact_requirements,
            self.claim_requirements,
            self.evidence_source_requirements,
            self.structural_object_obligations,
            self.project_specific_elements,
        )
        if not any(obligations):
            raise ValueError("SubstantiveContentContractV2 is vacuous")
        if (
            self.structural_object_obligations
            and not self.fact_requirements
            and not self.claim_requirements
            and not self.evidence_source_requirements
            and not self.project_specific_elements
        ):
            raise ValueError(
                "object-only content obligations require project-specific "
                "elements instead of generic title/paragraph presence"
            )
        positive = (
            any(item.obligation is FactObligation.REQUIRED for item in self.fact_requirements)
            or any(item.obligation is ClaimObligation.REQUIRED for item in self.claim_requirements)
            or self.evidence_source_requirements
            or self.project_specific_elements
        )
        if not positive:
            raise ValueError("content contract requires a positive substantive obligation")
        return self


class ChapterContractV2(StatefulProtocolV3Model):
    schema_version: Literal["mw_protocol_v3_contract_v2"] = (
        CHAPTER_CONTRACT_V2_SCHEMA_VERSION
    )
    chapter_contract_id: StableId
    semantic_node_id: StableId
    contract_version: NonEmptyText
    template_id: StableId
    template_sha256: Sha256
    chapter_skill_id: StableId
    chapter_skill_version: NonEmptyText
    substantive_content: SubstantiveContentContractV2
    word_rules: WordFormattingRules
    positive_qc_rules: Annotated[tuple[PositiveQcRule, ...], Field(min_length=1)]
    conditional_applicability_rules: tuple[ConditionalApplicabilityRule, ...] = ()
    dependency_ids: tuple[StableId, ...] = ()
    dependency_repair_policy: Optional[DependencyRepairPolicy] = None
    ctq_items: tuple[CriticalToQualityItem, ...] = ()
    patient_participation_obligations: tuple[PatientParticipationObligation, ...] = ()
    registry_consistency_obligations: tuple[RegistryConsistencyObligation, ...] = ()
    canonical_state: CanonicalState = CanonicalState.FROZEN

    @model_validator(mode="after")
    def validate_chapter_contract_v2(self) -> Self:
        if self.substantive_content.chapter_contract_id != self.chapter_contract_id:
            raise ValueError("substantive content belongs to a different chapter contract")
        _unique(
            tuple(item.positive_qc_rule_id for item in self.positive_qc_rules),
            "positive_qc_rule_ids",
        )
        _unique(
            tuple(
                item.conditional_applicability_rule_id
                for item in self.conditional_applicability_rules
            ),
            "conditional_applicability_rule_ids",
        )
        _unique(self.dependency_ids, "dependency_ids")
        _unique(tuple(item.ctq_item_id for item in self.ctq_items), "ctq_item_ids")
        _unique(
            tuple(
                item.patient_participation_obligation_id
                for item in self.patient_participation_obligations
            ),
            "patient_participation_obligation_ids",
        )
        _unique(
            tuple(
                item.registry_consistency_obligation_id
                for item in self.registry_consistency_obligations
            ),
            "registry_consistency_obligation_ids",
        )
        if self.dependency_ids and self.dependency_repair_policy is None:
            raise ValueError("declared dependencies require a repair policy and owner")
        if self.dependency_repair_policy is not None:
            undeclared = set(self.dependency_repair_policy.dependency_ids) - set(
                self.dependency_ids
            )
            if undeclared:
                raise ValueError(
                    "repair policy references undeclared dependency IDs"
                )
        declared_qc_rules = {
            item.positive_qc_rule_id for item in self.positive_qc_rules
        }
        for item in self.ctq_items:
            if set(item.positive_qc_rule_ids) - declared_qc_rules:
                raise ValueError(
                    "CtQ item references an unknown positive QC rule"
                )
        if self.canonical_state not in {
            CanonicalState.FROZEN,
            CanonicalState.SUPERSEDED,
            CanonicalState.QUARANTINED,
        }:
            raise ValueError("ChapterContractV2 must be frozen before execution")
        return self


__all__ = [
    "PROTOCOL_V3_SCHEMA_VERSION",
    "CHAPTER_CONTRACT_V2_SCHEMA_VERSION",
    "ActorType",
    "ApplicabilityEntry",
    "ApplicabilitySnapshot",
    "ApplicabilityStatus",
    "ArtifactDerivationKind",
    "CanonicalState",
    "ChapterContract",
    "ChapterContractV2",
    "ChapterLockSnapshot",
    "ClaimEvidenceLink",
    "ClaimObligation",
    "ClaimRequirement",
    "ConditionalApplicabilityRule",
    "CriticalToQualityItem",
    "DecisionRecord",
    "DependencyRepairPolicy",
    "DomainEvent",
    "EvidenceClass",
    "EvidenceRelation",
    "EvidenceSourceRequirement",
    "EvidenceUnit",
    "ExecutionReservation",
    "ExecutionTerminalState",
    "FactObligation",
    "FactRequirement",
    "LocatorKind",
    "MedicalAdmissionUnit",
    "NodeExecutionContract",
    "NormalizedResearchSeed",
    "PatientParticipationObligation",
    "PatientParticipationStatus",
    "PositiveQcRule",
    "ProjectionArtifact",
    "ProjectionKind",
    "ProtocolV3Model",
    "ReasoningEffort",
    "RecommendationOption",
    "RegistryConsistencyObligation",
    "RepairStep",
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
    "StructuralObjectObligation",
    "StudyDefinitionV3",
    "SubmissionEvidencePackage",
    "SubstantiveContentContract",
    "SubstantiveContentContractV2",
    "WordFormattingRules",
    "WorkflowRun",
    "WorkflowRunStatus",
    "assert_canonical_state_transition",
]
