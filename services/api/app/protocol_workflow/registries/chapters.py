"""Typed chapter registry core for Protocol v3 Task 3R.3.

This module is reusable registry infrastructure only.  It loads per-node
registries whose chapters embed the accepted :class:`ChapterContractV2`
payloads together with dedicated chapter-skill manifests, a closed fact/claim
vocabulary and executable positive/negative fixtures.  It deliberately does
NOT author clinical chapter content, call any product, or decide medical or
QC judgment: deterministic findings and unexecuted judgment obligations are
reported separately.

Compact JSON layout (documented by :func:`load_chapter_registry` and the
round-trip example in ``tests/protocol_v3/test_all_chapter_contracts.py``)::

    {
      "schema_version": "protocol-v3-chapter-registry.v1",
      "generated_for": "...", "authority": "...",
      "template_id": "tp_ma_07_v2",
      "template_sha256": "<frozen source sha256 of the accepted template>",
      "fact_vocabulary":  ["picos.objective.primary", ...],
      "claim_vocabulary": ["study_objective", ...],
      "chapters": [
        {"node_id": "v2_n_3_1_1",
         "coverage_role": "heading_leaf",
         "contract":   { ...ChapterContractV2 payload, embedded verbatim... },
         "skills":     [ { ...ChapterSkillManifest payload... } ]},
        ...
      ],
      "fixtures": [
        {"fixture_id": "fixture:objectives:positive",
         "chapter_contract_id": "contract:v2-n-3-1-1:v2",
         "fixture_kind": "positive",
         "content": {"facts": [...], "claims": [...],
                      "evidence": [...], "objects": [...]},
         "supplied_passed": null, "supplied_qc_verdict": null}
      ]
    }

``coverage_role`` is one of ``heading_leaf`` (leaf in both the heading-style
tree and the outlined tree), ``heading_only_aggregation`` (heading-tree-only
leaf such as the TP-MA-07 appendix container: aggregation/Word obligations,
not a content leaf), ``outline_only_leaf`` (glossary / concrete appendix
leaves), or ``cover`` (the unheaded front-block carrier).  Coverage truth is
always derived from the template ``node_tree.json`` at lint time; counts are
never hardcoded.

The chapter-skill manifests carry no model transport fields: provider/model
choice belongs to the approved role binding (``role_registry.json``), not to
an individual skill.  The skill I/O schemas are the concrete exported
Pydantic types :class:`ChapterSkillInput` and :class:`ChapterSkillOutput`;
manifest schema refs must name exactly those types.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    _freeze_json_value,
    ChapterContractV2,
    LocatorKind,
    SourceRole,
    StableId,
    StructuralObjectKind,
    Sha256,
    NonEmptyText,
    UnitInterval,
    WordFormattingRules,
)

from app.protocol_workflow.registries.loader import RegistryDocumentError, _scan_credentials

__all__ = [
    "CHAPTER_REGISTRY_SCHEMA_VERSION",
    "CHAPTER_SKILL_INPUT_SCHEMA_REF",
    "CHAPTER_SKILL_OUTPUT_SCHEMA_REF",
    "CheckerFinding",
    "ChapterContentPayload",
    "ChapterEntry",
    "ChapterFixture",
    "ChapterPromptContract",
    "ChapterRegistryDocument",
    "ChapterRegistryError",
    "ChapterSkillInput",
    "ChapterSkillManifest",
    "ChapterSkillOutput",
    "ContentCell",
    "ContentClaim",
    "ContentEvidence",
    "ContentFact",
    "ContentObject",
    "CoverageSummary",
    "FixtureCheckResult",
    "LintFinding",
    "LintInputError",
    "LintReport",
    "check_fixture",
    "check_skill_output",
    "evaluate_chapter_content",
    "lint_registry",
    "load_chapter_registry",
    "resolve_schema_ref",
]


CHAPTER_REGISTRY_SCHEMA_VERSION = "protocol-v3-chapter-registry.v1"

#: Canonical refs of the exported shared skill I/O schema types.  A manifest
#: must name exactly these refs; an invented schema URL is never treated as
#: implemented I/O.
_CHAPTER_IO_MODULE = "app.protocol_workflow.registries.chapters"
CHAPTER_SKILL_INPUT_SCHEMA_REF = f"{_CHAPTER_IO_MODULE}:ChapterSkillInput"
CHAPTER_SKILL_OUTPUT_SCHEMA_REF = f"{_CHAPTER_IO_MODULE}:ChapterSkillOutput"

CoverageRole = Literal[
    "heading_leaf", "heading_only_aggregation", "outline_only_leaf", "cover"
]

FixtureKind = Literal[
    "positive", "missing_claim", "missing_control", "wrong_source", "skeleton"
]


class ChapterRegistryError(RegistryDocumentError):
    """Raised when a chapter registry document fails closed."""


class LintInputError(ValueError):
    """Raised when the linter input template directory is unusable."""


# ---------------------------------------------------------------------------
# Shared typed skill I/O and content payload types.
# ---------------------------------------------------------------------------

def _is_resolved_fact(value: JsonValue) -> bool:
    """Transport supplied JSON intact; content sufficiency is checked separately."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _has_fact_value(value: JsonValue) -> bool:
    """Content presence, not truthiness or proof of medical correctness."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_fact_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_fact_value(item) for item in value)
    return True  # Both false and zero are real supplied facts.


class ContentFact(BaseModel):
    """A supplied fact value.  ``value`` may be absent, None or blank — all of
    which fail any required-fact obligation (existence alone is insufficient);
    blankness is decided by the checker, not silently repaired here."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    fact_path: NonEmptyText
    value: JsonValue = None

    @field_validator("value")
    @classmethod
    def _immutable_value(cls, value: JsonValue) -> JsonValue:
        return _freeze_json_value(value)


class ContentClaim(BaseModel):
    """A supplied claim statement.  A blank/absent statement is not content
    and fails any required-claim obligation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    claim_type: NonEmptyText
    statement: Optional[str] = None


class ContentEvidence(BaseModel):
    """A supplied evidence unit: role, admitted claim, locator, context and
    quality against the chapter's evidence floor."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_role: SourceRole
    admission_claim_type: NonEmptyText
    locator_kind: LocatorKind
    locator: NonEmptyText
    context: Optional[str] = None
    quality_score: UnitInterval


class ContentCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    cell_id: StableId
    value: Optional[str] = None


class ContentObject(BaseModel):
    """A supplied structural object.  ``occurrences`` counts instances; an
    object is material only when it carries non-blank text or at least one
    non-blank cell, so ID-only shells never satisfy obligations."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    object_kind: StructuralObjectKind
    occurrences: int = Field(ge=0)
    text: Optional[str] = None
    cells: tuple[ContentCell, ...] = ()

    @field_validator("cells")
    @classmethod
    def _unique_cells(cls, value: tuple[ContentCell, ...]) -> tuple[ContentCell, ...]:
        cell_ids = [cell.cell_id for cell in value]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("cells must not contain duplicate cell ids")
        return value

    def is_material(self) -> bool:
        return bool((self.text or "").strip()) or any(
            (cell.value or "").strip() for cell in self.cells
        )


class ChapterContentPayload(BaseModel):
    """The actual supplied content a fixture or skill output claims."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    facts: tuple[ContentFact, ...] = ()
    claims: tuple[ContentClaim, ...] = ()
    evidence: tuple[ContentEvidence, ...] = ()
    objects: tuple[ContentObject, ...] = ()

    @field_validator("facts")
    @classmethod
    def _unique_facts(cls, value: tuple[ContentFact, ...]) -> tuple[ContentFact, ...]:
        paths = [item.fact_path for item in value]
        if len(paths) != len(set(paths)):
            raise ValueError("facts must not contain duplicate fact paths")
        return value

    @field_validator("claims")
    @classmethod
    def _unique_claims(cls, value: tuple[ContentClaim, ...]) -> tuple[ContentClaim, ...]:
        types = [item.claim_type for item in value]
        if len(types) != len(set(types)):
            raise ValueError("claims must not contain duplicate claim types")
        return value


class ChapterSkillInput(BaseModel):
    """Shared typed input handed to a chapter skill.

    The resolved facts are already-confirmed project facts; the skill never
    invents them.  Model/provider selection is owned by the role binding and
    is intentionally absent here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    chapter_contract_id: StableId
    node_id: StableId
    template_id: StableId
    template_sha256: Sha256
    resolved_facts: Mapping[str, JsonValue] = Field(min_length=1)
    active_conditional_rule_ids: tuple[StableId, ...] = ()
    word_rules: WordFormattingRules

    @field_validator("resolved_facts")
    @classmethod
    def _facts_non_blank(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        for path, resolved in value.items():
            if not _is_resolved_fact(resolved):
                raise ValueError(
                    f"resolved_facts[{path!r}] must carry a non-blank value"
                )
        return MappingProxyType(
            {path: _freeze_json_value(resolved) for path, resolved in value.items()}
        )

    @field_serializer("resolved_facts")
    def _serialize_facts(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return dict(value)


class ChapterSkillOutput(BaseModel):
    """Shared typed output produced by a chapter skill.

    ``self_reported_passed`` / ``self_reported_qc_verdict`` are recorded for
    traceability and are never consulted when determining whether the output
    satisfies the chapter contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    chapter_contract_id: StableId
    node_id: StableId
    facts: tuple[ContentFact, ...] = ()
    claims: tuple[ContentClaim, ...] = ()
    evidence: tuple[ContentEvidence, ...] = ()
    objects: tuple[ContentObject, ...] = ()
    self_reported_passed: Optional[bool] = None
    self_reported_qc_verdict: Optional[str] = None

    def content_payload(self) -> ChapterContentPayload:
        return ChapterContentPayload(
            facts=self.facts,
            claims=self.claims,
            evidence=self.evidence,
            objects=self.objects,
        )


def resolve_schema_ref(ref: str) -> type[BaseModel]:
    """Resolve a ``module:TypeName`` schema ref to the exported Pydantic type."""
    module_name, _, type_name = ref.partition(":")
    if not module_name or not type_name:
        raise ChapterRegistryError(f"malformed schema ref: {ref!r}")
    try:
        module = importlib.import_module(module_name)
        resolved = getattr(module, type_name)
    except (ImportError, AttributeError) as exc:
        raise ChapterRegistryError(f"schema ref does not resolve: {ref!r}") from exc
    if not (isinstance(resolved, type) and issubclass(resolved, BaseModel)):
        raise ChapterRegistryError(f"schema ref is not a Pydantic model: {ref!r}")
    return resolved


class ChapterPromptContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    prompt_version: NonEmptyText
    instructions: NonEmptyText
    forbidden_behaviors: tuple[NonEmptyText, ...] = Field(min_length=1)

    @field_validator("forbidden_behaviors")
    @classmethod
    def _unique_behaviors(
        cls, value: tuple[NonEmptyText, ...]
    ) -> tuple[NonEmptyText, ...]:
        if len(value) != len(set(value)):
            raise ValueError("forbidden_behaviors must not contain duplicates")
        return value


class ChapterSkillManifest(BaseModel):
    """A dedicated chapter-skill manifest.

    Unique ``skill_id``/``skill_version`` bound to the semantic node, the
    chapter contract and the accepted template identity.  Carries no model
    transport fields: provider/model choice belongs to the approved role
    binding.  The schema refs are closed to the concrete exported shared
    I/O types; errors and provenance requirements are stable obligations.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    skill_id: StableId
    skill_version: NonEmptyText
    node_id: StableId
    chapter_contract_id: StableId
    template_id: StableId
    template_sha256: Sha256
    input_schema_ref: Literal[CHAPTER_SKILL_INPUT_SCHEMA_REF]  # type: ignore[valid-type]
    output_schema_ref: Literal[CHAPTER_SKILL_OUTPUT_SCHEMA_REF]  # type: ignore[valid-type]
    prompt_contract: ChapterPromptContract
    provenance_requirements: tuple[NonEmptyText, ...] = Field(min_length=1)
    error_codes: tuple[StableId, ...] = Field(min_length=1)

    @field_validator("error_codes")
    @classmethod
    def _unique_error_codes(cls, value: tuple[StableId, ...]) -> tuple[StableId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("error_codes must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _schema_refs_resolve(self) -> ChapterSkillManifest:
        if resolve_schema_ref(self.input_schema_ref) is not ChapterSkillInput:
            raise ValueError("input_schema_ref must resolve to ChapterSkillInput")
        if resolve_schema_ref(self.output_schema_ref) is not ChapterSkillOutput:
            raise ValueError("output_schema_ref must resolve to ChapterSkillOutput")
        return self


# ---------------------------------------------------------------------------
# Registry document.
# ---------------------------------------------------------------------------


class ChapterFixture(BaseModel):
    """An executable positive/negative fixture bound to a chapter contract.

    ``fixture_kind`` names the defect a negative fixture exercises (or
    ``positive``); ``supplied_passed`` / ``supplied_qc_verdict`` are recorded
    and ignored by the deterministic checker.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    fixture_id: StableId
    chapter_contract_id: StableId
    fixture_kind: FixtureKind
    content: ChapterContentPayload
    supplied_passed: Optional[bool] = None
    supplied_qc_verdict: Optional[str] = None


class ChapterEntry(BaseModel):
    """One semantic node carrier: embedded contract plus companion skills."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    node_id: StableId
    coverage_role: CoverageRole
    contract: ChapterContractV2
    skills: tuple[ChapterSkillManifest, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bind_identities(self) -> ChapterEntry:
        if self.contract.semantic_node_id != self.node_id:
            raise ValueError(
                f"contract {self.contract.chapter_contract_id!r} is bound to node "
                f"{self.contract.semantic_node_id!r}, not {self.node_id!r}"
            )
        skill_ids = [skill.skill_id for skill in self.skills]
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("duplicate skill ids within one chapter entry")
        for skill in self.skills:
            if skill.node_id != self.node_id:
                raise ValueError(
                    f"skill {skill.skill_id!r} is bound to node {skill.node_id!r}, "
                    f"not {self.node_id!r}"
                )
            if skill.chapter_contract_id != self.contract.chapter_contract_id:
                raise ValueError(
                    f"skill {skill.skill_id!r} is bound to contract "
                    f"{skill.chapter_contract_id!r}, not "
                    f"{self.contract.chapter_contract_id!r}"
                )
            if skill.template_id != self.contract.template_id:
                raise ValueError(
                    f"skill {skill.skill_id!r} template identity differs from the "
                    f"chapter contract"
                )
            if skill.template_sha256 != self.contract.template_sha256:
                raise ValueError(
                    f"skill {skill.skill_id!r} template hash differs from the "
                    f"chapter contract"
                )
        return self


class ChapterRegistryDocument(BaseModel):
    """Closed, versioned chapter registry document."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[CHAPTER_REGISTRY_SCHEMA_VERSION]  # type: ignore[valid-type]
    generated_for: NonEmptyText
    authority: NonEmptyText
    template_id: StableId
    template_sha256: Sha256
    fact_vocabulary: tuple[NonEmptyText, ...] = Field(min_length=1)
    claim_vocabulary: tuple[NonEmptyText, ...] = Field(min_length=1)
    chapters: tuple[ChapterEntry, ...] = Field(min_length=1)
    fixtures: tuple[ChapterFixture, ...] = ()

    @field_validator("fact_vocabulary", "claim_vocabulary")
    @classmethod
    def _vocab_closed(
        cls, value: tuple[NonEmptyText, ...], info: Any
    ) -> tuple[NonEmptyText, ...]:
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _cross_document_identity(self) -> ChapterRegistryDocument:
        node_ids = [entry.node_id for entry in self.chapters]
        if len(node_ids) != len(set(node_ids)):
            duplicates = sorted({nid for nid in node_ids if node_ids.count(nid) > 1})
            raise ValueError(f"duplicate chapter node ids: {duplicates}")
        contract_ids = [entry.contract.chapter_contract_id for entry in self.chapters]
        if len(contract_ids) != len(set(contract_ids)):
            duplicates = sorted({cid for cid in contract_ids if contract_ids.count(cid) > 1})
            raise ValueError(f"duplicate chapter contract ids: {duplicates}")
        skill_ids = [
            skill.skill_id for entry in self.chapters for skill in entry.skills
        ]
        if len(skill_ids) != len(set(skill_ids)):
            duplicates = sorted({sid for sid in skill_ids if skill_ids.count(sid) > 1})
            raise ValueError(f"duplicate skill ids: {duplicates}")
        for entry in self.chapters:
            if entry.contract.template_id != self.template_id:
                raise ValueError(
                    f"chapter {entry.node_id!r} template_id differs from the registry"
                )
            if entry.contract.template_sha256 != self.template_sha256:
                raise ValueError(
                    f"chapter {entry.node_id!r} template_sha256 differs from the registry"
                )
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            duplicates = sorted({fid for fid in fixture_ids if fixture_ids.count(fid) > 1})
            raise ValueError(f"duplicate fixture ids: {duplicates}")
        declared = set(contract_ids)
        for fixture in self.fixtures:
            if fixture.chapter_contract_id not in declared:
                raise ValueError(
                    f"fixture {fixture.fixture_id!r} binds unknown chapter contract "
                    f"{fixture.chapter_contract_id!r}"
                )
        return self


def _load_json(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return json.loads(json.dumps(dict(source), ensure_ascii=False, sort_keys=True))
    path = Path(source)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ChapterRegistryError(f"chapter registry unreadable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ChapterRegistryError(f"chapter registry is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ChapterRegistryError(
            f"chapter registry must be a JSON object; got {type(data).__name__}"
        )
    return data


def load_chapter_registry(
    source: str | Path | Mapping[str, Any],
) -> ChapterRegistryDocument:
    """Load and validate a chapter registry document fail-closed.

    Raises :class:`ChapterRegistryError` (a ``ValueError``) for any closed-set,
    schema-version, duplicate, identity-binding or vocabulary violation.
    """
    data = _load_json(source)
    _scan_credentials(data, "chapter-registry")
    try:
        document = ChapterRegistryDocument.model_validate(data)
    except ValidationError as exc:
        raise ChapterRegistryError(
            f"chapter registry failed closed: {exc}"
        ) from exc
    return document


# ---------------------------------------------------------------------------
# Deterministic fixture / skill-output checker.
# ---------------------------------------------------------------------------


class CheckerFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Literal["error", "warning", "info"]
    location: str
    message: str


class FixtureCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    chapter_contract_id: str
    passed: bool
    findings: tuple[CheckerFinding, ...] = ()
    #: Unexecuted medical/QC judgment obligations, always listed explicitly.
    deferred_qc_obligations: tuple[str, ...] = ()
    #: True when the payload carried supplied verdicts that were ignored.
    ignored_supplied_verdict: bool = False

    def error_codes(self) -> tuple[str, ...]:
        return tuple(
            finding.code for finding in self.findings if finding.severity == "error"
        )


def _finding(code: str, location: str, message: str) -> CheckerFinding:
    return CheckerFinding(
        code=code, severity="error", location=location, message=message
    )


def _material_occurrences(payload: ChapterContentPayload, kind: str) -> int:
    return sum(
        obj.occurrences
        for obj in payload.objects
        if obj.object_kind.value == kind and obj.is_material()
    )


def evaluate_chapter_content(
    contract: ChapterContractV2,
    content: ChapterContentPayload,
    *,
    subject_id: str,
    supplied_passed: Optional[bool] = None,
    supplied_qc_verdict: Optional[str] = None,
) -> FixtureCheckResult:
    """Deterministically check supplied content against a chapter contract.

    Only shape/positivity/source-floor violations are decided here.  Positive
    QC rules, CtQ items and skeleton-risk rules that require medical judgment
    are returned as ``deferred_qc_obligations`` and are never counted as
    evaluated.  Supplied ``passed`` flags and QC verdict strings are ignored.
    """
    findings: list[CheckerFinding] = []
    substantive = contract.substantive_content

    facts_by_path = {fact.fact_path: fact for fact in content.facts}
    claims_by_type = {claim.claim_type: claim for claim in content.claims}

    for index, requirement in enumerate(substantive.fact_requirements):
        location = f"contract.fact_requirements[{index}]({requirement.fact_path})"
        supplied = facts_by_path.get(requirement.fact_path)
        has_value = supplied is not None and _has_fact_value(supplied.value)
        if requirement.obligation.value == "required" and not has_value:
            findings.append(
                _finding(
                    "missing_required_fact",
                    location,
                    "required fact is absent, null or blank; key existence alone "
                    "is insufficient",
                )
            )
        if requirement.obligation.value == "forbidden" and has_value:
            findings.append(
                _finding(
                    "forbidden_fact_present",
                    location,
                    "forbidden fact path carries actual content",
                )
            )

    for index, requirement in enumerate(substantive.claim_requirements):
        location = f"contract.claim_requirements[{index}]({requirement.claim_type})"
        supplied = claims_by_type.get(requirement.claim_type)
        has_statement = supplied is not None and bool(
            (supplied.statement or "").strip()
        )
        if requirement.obligation.value == "required" and not has_statement:
            findings.append(
                _finding(
                    "missing_required_claim",
                    location,
                    "required claim is absent or its statement is empty",
                )
            )
        if requirement.obligation.value == "forbidden" and has_statement:
            findings.append(
                _finding(
                    "forbidden_claim_present",
                    location,
                    "forbidden claim type carries an actual statement",
                )
            )
        if requirement.obligation.value == "qualified" and has_statement:
            findings.append(
                CheckerFinding(
                    code="qualified_claim_needs_review",
                    severity="info",
                    location=location,
                    message=(
                        "qualified claim present; qualifying conditions require "
                        "medical judgment not executed here"
                    ),
                )
            )

    requirements = substantive.evidence_source_requirements
    for group_index, group in enumerate(requirements):
        group_location = f"contract.evidence_source_requirements[{group_index}]"
        roles = {role.value for role in group.source_roles}
        admissions = set(group.admission_claim_types)
        locators = {kind.value for kind in group.allowed_locator_kinds}
        conforming = False
        for item_index, item in enumerate(content.evidence):
            item_location = f"{group_location}.supplied[{item_index}]"
            if item.admission_claim_type not in admissions:
                continue
            if item.source_role.value not in roles and any(
                item.source_role in other.source_roles
                and item.admission_claim_type in other.admission_claim_types
                for other in requirements
            ):
                continue
            if item.admission_claim_type in admissions and item.source_role.value not in roles:
                findings.append(
                    _finding(
                        "wrong_source_role",
                        item_location,
                        f"source role {item.source_role.value!r} may not admit "
                        f"claim {item.admission_claim_type!r}",
                    )
                )
            if item.locator_kind.value not in locators:
                findings.append(
                    _finding(
                        "disallowed_locator",
                        item_location,
                        f"locator kind {item.locator_kind.value!r} is not allowed",
                    )
                )
            if group.require_context_window and not (item.context or "").strip():
                findings.append(
                    _finding(
                        "missing_context_window",
                        item_location,
                        "evidence floor requires a non-blank context window",
                    )
                )
            if item.quality_score < group.minimum_quality_score:
                findings.append(
                    _finding(
                        "insufficient_quality",
                        item_location,
                        f"quality score {item.quality_score} is below the floor "
                        f"{group.minimum_quality_score}",
                    )
                )
            if (
                item.source_role.value in roles
                and item.admission_claim_type in admissions
                and item.locator_kind.value in locators
                and (not group.require_context_window or (item.context or "").strip())
                and item.quality_score >= group.minimum_quality_score
            ):
                conforming = True
        if not conforming:
            findings.append(
                _finding(
                    "unsatisfied_evidence_requirement",
                    group_location,
                    "no supplied evidence unit satisfies this evidence floor",
                )
            )
    if requirements:
        declared_admissions = {
            claim for group in requirements for claim in group.admission_claim_types
        }
        declared_roles = {
            role.value for group in requirements for role in group.source_roles
        }
        for item_index, item in enumerate(content.evidence):
            if item.admission_claim_type not in declared_admissions and item.source_role.value in declared_roles:
                findings.append(_finding(
                    "inadmissible_claim", f"content.evidence[{item_index}]",
                    "claim is not admitted by any declared evidence requirement",
                ))
            if (
                item.admission_claim_type not in declared_admissions
                and item.source_role.value not in declared_roles
            ):
                findings.append(
                    CheckerFinding(
                        code="undeclared_evidence_source",
                        severity="warning",
                        location=f"content.evidence[{item_index}]",
                        message="evidence unit maps to no declared evidence floor",
                    )
                )

    for index, obligation in enumerate(substantive.structural_object_obligations):
        location = (
            f"contract.structural_object_obligations[{index}]"
            f"({obligation.object_kind.value})"
        )
        material = _material_occurrences(content, obligation.object_kind.value)
        if material < obligation.minimum_occurrences:
            findings.append(
                _finding(
                    "missing_structural_object",
                    location,
                    f"material occurrences {material} are below the required "
                    f"{obligation.minimum_occurrences}; ID-only shells do not count",
                )
            )
        supplied_cells = {
            cell.cell_id: cell
            for obj in content.objects
            if obj.object_kind.value == obligation.object_kind.value
            for cell in obj.cells
        }
        for cell_id in obligation.required_object_cells:
            cell = supplied_cells.get(cell_id)
            if cell is None or not (cell.value or "").strip():
                findings.append(
                    _finding(
                        "missing_required_cell",
                        f"{location}.cell({cell_id})",
                        "required cell is absent, null or blank",
                    )
                )

    required_fact_paths = {
        item.fact_path
        for item in substantive.fact_requirements
        if item.obligation.value == "required"
    }
    required_claim_types = {
        item.claim_type
        for item in substantive.claim_requirements
        if item.obligation.value == "required"
    }
    has_any_positive_content = (
        any(
            _has_fact_value(fact.value)
            for fact in content.facts
            if fact.fact_path in required_fact_paths
        )
        or any(
            (claim.statement or "").strip()
            for claim in content.claims
            if claim.claim_type in required_claim_types
        )
        or any(obj.is_material() for obj in content.objects)
    )
    if not has_any_positive_content:
        findings.append(
            _finding(
                "skeleton_content",
                "content",
                "no required fact value, claim statement or material object is "
                "present; title/skeleton-only output fails",
            )
        )

    known_fact_paths = {item.fact_path for item in substantive.fact_requirements}
    known_claim_types = {item.claim_type for item in substantive.claim_requirements}
    for index, fact in enumerate(content.facts):
        if fact.fact_path not in known_fact_paths:
            findings.append(
                CheckerFinding(
                    code="undeclared_fact_path",
                    severity="warning",
                    location=f"content.facts[{index}]({fact.fact_path})",
                    message="fact path is not declared by this chapter contract",
                )
            )
    for index, claim in enumerate(content.claims):
        if claim.claim_type not in known_claim_types:
            findings.append(
                CheckerFinding(
                    code="undeclared_claim_type",
                    severity="warning",
                    location=f"content.claims[{index}]({claim.claim_type})",
                    message="claim type is not declared by this chapter contract",
                )
            )

    deferred: list[str] = ["medical_and_qc_judgment_not_executed"]
    for rule in contract.positive_qc_rules:
        deferred.append(f"positive_qc_rule:{rule.positive_qc_rule_id}: {rule.rule}")
    for item in contract.ctq_items:
        deferred.append(f"ctq:{item.ctq_item_id}: {item.question}")
    for rule in substantive.skeleton_risk_rules:
        deferred.append(f"skeleton_risk_rule: {rule}")
    for rule in contract.conditional_applicability_rules:
        deferred.append(f"conditional_applicability_not_executed:{rule.conditional_applicability_rule_id}")
    for element in substantive.project_specific_elements:
        deferred.append(f"project_specific_element_not_evaluated: {element}")

    ignored = supplied_passed is not None or supplied_qc_verdict is not None
    return FixtureCheckResult(
        subject_id=subject_id,
        chapter_contract_id=contract.chapter_contract_id,
        passed=not any(f.severity == "error" for f in findings),
        findings=tuple(findings),
        deferred_qc_obligations=tuple(deferred),
        ignored_supplied_verdict=ignored,
    )


def _contract_index(
    document: ChapterRegistryDocument,
) -> dict[str, ChapterContractV2]:
    return {
        entry.contract.chapter_contract_id: entry.contract for entry in document.chapters
    }


def check_fixture(
    document: ChapterRegistryDocument, fixture: ChapterFixture
) -> FixtureCheckResult:
    """Run the deterministic checker for one fixture against its chapter."""
    contract = _contract_index(document).get(fixture.chapter_contract_id)
    if contract is None:
        raise ChapterRegistryError(
            f"fixture {fixture.fixture_id!r} binds unknown chapter contract "
            f"{fixture.chapter_contract_id!r}"
        )
    return evaluate_chapter_content(
        contract,
        fixture.content,
        subject_id=fixture.fixture_id,
        supplied_passed=fixture.supplied_passed,
        supplied_qc_verdict=fixture.supplied_qc_verdict,
    )


def check_skill_output(
    document: ChapterRegistryDocument, output: ChapterSkillOutput
) -> FixtureCheckResult:
    """Run the deterministic checker for a skill output against its chapter."""
    contract = _contract_index(document).get(output.chapter_contract_id)
    if contract is None:
        raise ChapterRegistryError(
            f"skill output binds unknown chapter contract "
            f"{output.chapter_contract_id!r}"
        )
    if output.node_id != contract.semantic_node_id:
        return FixtureCheckResult(
            subject_id=f"skill_output:{output.node_id}",
            chapter_contract_id=contract.chapter_contract_id,
            passed=False,
            findings=(_finding("output_node_mismatch", "output.node_id",
                               "output belongs to a different semantic node"),),
            deferred_qc_obligations=("medical_and_qc_judgment_not_executed",),
        )
    return evaluate_chapter_content(
        contract,
        output.content_payload(),
        subject_id=f"skill_output:{output.node_id}",
        supplied_passed=output.self_reported_passed,
        supplied_qc_verdict=output.self_reported_qc_verdict,
    )


def _fixture_matches(contract: ChapterContractV2, fixture: ChapterFixture,
                     result: FixtureCheckResult) -> bool:
    if fixture.fixture_kind == "positive":
        return result.passed
    substantive = contract.substantive_content
    missing: set[str] = set()
    if any(item.obligation.value == "required" for item in substantive.fact_requirements):
        missing.add("missing_required_fact")
    if any(item.obligation.value == "required" for item in substantive.claim_requirements):
        missing.add("missing_required_claim")
    if substantive.evidence_source_requirements:
        missing.add("unsatisfied_evidence_requirement")
    if substantive.structural_object_obligations:
        missing.add("missing_structural_object")
    if any(item.required_object_cells for item in substantive.structural_object_obligations):
        missing.add("missing_required_cell")
    expected = {
        "missing_claim": missing & {"missing_required_claim"},
        "missing_control": missing,
        "wrong_source": {"wrong_source_role", "inadmissible_claim", "disallowed_locator",
                         "missing_context_window", "insufficient_quality"},
        "skeleton": {"skeleton_content", "missing_structural_object", "missing_required_cell"},
    }[fixture.fixture_kind]
    return not result.passed and bool(set(result.error_codes()) & expected)


# ---------------------------------------------------------------------------
# Cross-contract linter.
# ---------------------------------------------------------------------------


class LintFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Literal["error", "warning", "info"]
    node_id: Optional[str] = None
    location: str
    message: str


class CoverageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heading_leaf_count: int
    heading_only_aggregation_count: int
    outline_only_leaf_count: int
    leaf_union_count: int
    expected_carrier_count: int
    covered_carrier_count: int
    cover_node_id: Optional[str] = None
    missing_node_ids: tuple[str, ...] = ()
    unexpected_node_ids: tuple[str, ...] = ()


class LintReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["full", "partial"]
    status: Literal["complete", "incomplete"]
    findings: tuple[LintFinding, ...] = ()
    coverage: CoverageSummary
    fixture_results: tuple[FixtureCheckResult, ...] = ()

    def errors(self) -> tuple[LintFinding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")


def _expected_roles_from_template(
    node_tree: Mapping[str, Any],
) -> tuple[dict[str, str], bool]:
    heading_nodes = (node_tree.get("heading_style_tree") or {}).get("nodes") or []
    outlined_nodes = (node_tree.get("outlined_tree") or {}).get("nodes") or []
    heading_leaves = {
        node["id"] for node in heading_nodes if node.get("is_leaf_heading")
    }
    outline_leaves = {node["id"] for node in outlined_nodes if node.get("is_leaf")}
    roles: dict[str, str] = {}
    for node_id in heading_leaves | outline_leaves:
        in_heading = node_id in heading_leaves
        in_outline = node_id in outline_leaves
        if in_heading and in_outline:
            roles[node_id] = "heading_leaf"
        elif in_heading:
            roles[node_id] = "heading_only_aggregation"
        else:
            roles[node_id] = "outline_only_leaf"
    has_front_block = bool(node_tree.get("front_block"))
    return roles, has_front_block


def _load_template_inputs(template_dir: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = Path(template_dir)
    node_tree_path = directory / "node_tree.json"
    template_path = directory / "template.json"
    try:
        node_tree = json.loads(node_tree_path.read_text(encoding="utf-8"))
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LintInputError(
            f"template directory must contain readable node_tree.json and "
            f"template.json: {directory}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LintInputError(f"template input is not valid JSON: {directory}") from exc
    source = template.get("source") or {}
    if not template.get("template_id") or not source.get("sha256"):
        raise LintInputError(
            f"template.json must declare template_id and source.sha256: {template_path}"
        )
    return node_tree, template


def lint_registry(
    template_dir: str | Path,
    registry: ChapterRegistryDocument,
    *,
    require_complete: bool = True,
) -> LintReport:
    """Cross-contract lint of a chapter registry against the template.

    Coverage truth derives from the template ``node_tree.json``: the union of
    heading-tree ``is_leaf_heading`` and outlined-tree ``is_leaf`` leaves plus
    the explicit unheaded cover carrier.  Counts are computed, never
    hardcoded, and ``is_leaf`` on heading-only nodes is never used as
    coverage.

    Full mode (``require_complete=True``) reports every coverage gap as an
    error.  Partial mode validates the submitted batch but always reports the
    registry incomplete and never represents full acceptance: its status is
    ``"incomplete"`` by construction.
    """
    node_tree, template = _load_template_inputs(template_dir)
    expected_roles, has_front_block = _expected_roles_from_template(node_tree)
    template_id = str(template["template_id"])
    template_sha = str(template["source"]["sha256"])
    mapping_path = Path(template_dir) / "v1_to_v2_mapping.json"
    expected_cover_id = None
    if mapping_path.exists():
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            cover_ids = {
                node for row in mapping["forward_mapping"]
                if row.get("semantic_node_id") == "document_control.front_matter"
                for node in row["target_v2_node_ids"]
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LintInputError("cannot resolve cover identity from template mapping") from exc
        if len(cover_ids) != 1:
            raise LintInputError("template mapping must identify one front-matter carrier")
        expected_cover_id = next(iter(cover_ids))

    findings: list[LintFinding] = []

    def add(code: str, severity: str, location: str, message: str, node_id: str | None = None) -> None:
        findings.append(
            LintFinding(
                code=code,
                severity=severity,  # type: ignore[arg-type]
                node_id=node_id,
                location=location,
                message=message,
            )
        )

    # --- template identity -------------------------------------------------
    if registry.template_id != template_id:
        add(
            "template_id_mismatch",
            "error",
            "registry.template_id",
            f"registry binds {registry.template_id!r} but the template dir "
            f"declares {template_id!r}",
        )
    if registry.template_sha256 != template_sha:
        add(
            "template_hash_mismatch",
            "error",
            "registry.template_sha256",
            "registry template hash differs from the frozen template source hash",
        )

    covered: dict[str, str] = {}
    declared_contract_ids: set[str] = set()
    cover_entries: list[ChapterEntry] = []
    for entry in registry.chapters:
        node_id = entry.node_id
        contract = entry.contract
        declared_contract_ids.add(contract.chapter_contract_id)
        if entry.coverage_role == "cover":
            cover_entries.append(entry)
            if expected_cover_id and node_id != expected_cover_id:
                add("cover_identity_mismatch", "error", f"chapters[{node_id}].node_id",
                    f"accepted mapping identifies cover {expected_cover_id!r}", node_id)
            if node_id in expected_roles:
                add(
                    "unexpected_carrier",
                    "error",
                    f"chapters[{node_id}].coverage_role",
                    "the cover carrier must be the unheaded front block, not a "
                    "node from the leaf union",
                    node_id,
                )
            covered.setdefault(node_id, "cover")
        if node_id not in expected_roles and entry.coverage_role != "cover":
            add(
                "unexpected_carrier",
                "error",
                f"chapters[{node_id}].node_id",
                "carrier is not in the derived leaf union; mid-tree headings "
                "are not coverage",
                node_id,
            )
            continue
        expected_role = expected_roles.get(node_id, "cover")
        if entry.coverage_role != expected_role:
            add(
                "coverage_role_mismatch",
                "error",
                f"chapters[{node_id}].coverage_role",
                f"declared role {entry.coverage_role!r} contradicts the derived "
                f"role {expected_role!r}",
                node_id,
            )
        covered.setdefault(node_id, entry.coverage_role)

        if contract.template_id != template_id:
            add(
                "template_id_mismatch",
                "error",
                f"chapters[{node_id}].contract.template_id",
                f"contract binds {contract.template_id!r}, expected {template_id!r}",
                node_id,
            )
        if contract.template_sha256 != template_sha:
            add(
                "template_hash_mismatch",
                "error",
                f"chapters[{node_id}].contract.template_sha256",
                "contract template hash differs from the frozen template source hash",
                node_id,
            )

        bound_skill_ids = {skill.skill_id for skill in entry.skills}
        if contract.chapter_skill_id not in bound_skill_ids:
            add(
                "skill_not_bound",
                "error",
                f"chapters[{node_id}].contract.chapter_skill_id",
                f"contract declares skill {contract.chapter_skill_id!r} but no "
                f"companion manifest provides it",
                node_id,
            )
        for skill in entry.skills:
            if skill.skill_id == contract.chapter_skill_id and skill.skill_version != contract.chapter_skill_version:
                add("skill_version_mismatch", "error",
                    f"chapters[{node_id}].contract.chapter_skill_version",
                    "companion skill version differs from the declared contract version", node_id)

        # --- closed vocabulary -------------------------------------------------
        substantive = contract.substantive_content
        declared_fact_paths = {item.fact_path for item in substantive.fact_requirements}
        conditional_fact_paths = {
            path
            for rule in contract.conditional_applicability_rules
            for path in (*rule.triggering_fact_paths, *rule.required_when_active_fact_paths)
        }
        ctq_fact_paths = {
            path for item in contract.ctq_items for path in item.linked_fact_paths
        }
        registry_fact_paths = {
            path
            for obligation in contract.registry_consistency_obligations
            for path in obligation.eligibility_fact_paths
        }
        used_fact_paths = (
            declared_fact_paths | conditional_fact_paths | ctq_fact_paths | registry_fact_paths
        )
        for path in sorted(used_fact_paths - set(registry.fact_vocabulary)):
            add(
                "unknown_fact_path",
                "error",
                f"chapters[{node_id}].contract.fact_paths({path})",
                "fact path is not a member of the registry fact vocabulary",
                node_id,
            )
        declared_claim_types = {
            item.claim_type for item in substantive.claim_requirements
        }
        conditional_claim_types = {
            claim for rule in contract.conditional_applicability_rules
            for claim in rule.required_when_active_claim_types
        }
        evidence_claim_types = {
            claim for requirement in substantive.evidence_source_requirements
            for claim in requirement.admission_claim_types
        }
        ctq_claim_types = {
            claim for item in contract.ctq_items for claim in item.linked_claim_types
        }
        for claim in sorted((declared_claim_types | ctq_claim_types | conditional_claim_types | evidence_claim_types) - set(registry.claim_vocabulary)):
            add(
                "unknown_claim_type",
                "error",
                f"chapters[{node_id}].contract.claim_types({claim})",
                "claim type is not a member of the registry claim vocabulary",
                node_id,
            )

        # --- conditional required vs forbidden contradictions ------------------
        forbidden_fact_paths = {
            item.fact_path
            for item in substantive.fact_requirements
            if item.obligation.value == "forbidden"
        }
        forbidden_claim_types = {
            item.claim_type
            for item in substantive.claim_requirements
            if item.obligation.value == "forbidden"
        }
        for rule in contract.conditional_applicability_rules:
            rule_location = (
                f"chapters[{node_id}].conditional_applicability_rules"
                f"({rule.conditional_applicability_rule_id})"
            )
            for path in sorted(set(rule.required_when_active_fact_paths) & forbidden_fact_paths):
                add(
                    "conditional_forbidden_conflict",
                    "error",
                    rule_location,
                    f"rule requires fact {path!r} when active, but the contract "
                    f"forbids it",
                    node_id,
                )
            for claim in sorted(
                set(rule.required_when_active_claim_types) & forbidden_claim_types
            ):
                add(
                    "conditional_forbidden_conflict",
                    "error",
                    rule_location,
                    f"rule requires claim {claim!r} when active, but the contract "
                    f"forbids it",
                    node_id,
                )
            for path in sorted(set(rule.triggering_fact_paths) & forbidden_fact_paths):
                add(
                    "conditional_forbidden_conflict",
                    "error",
                    rule_location,
                    f"rule triggers on forbidden fact {path!r}",
                    node_id,
                )

        # --- CtQ anchors --------------------------------------------------------
        anchorable_facts = declared_fact_paths | conditional_fact_paths
        anchorable_claims = declared_claim_types | conditional_claim_types
        for item in contract.ctq_items:
            for path in sorted(set(item.linked_fact_paths) - anchorable_facts):
                add(
                    "dangling_ctq_anchor",
                    "error",
                    f"chapters[{node_id}].ctq_items({item.ctq_item_id})",
                    f"CtQ item anchors unknown fact path {path!r}",
                    node_id,
                )
            for claim in sorted(set(item.linked_claim_types) - anchorable_claims):
                add(
                    "dangling_ctq_anchor",
                    "error",
                    f"chapters[{node_id}].ctq_items({item.ctq_item_id})",
                    f"CtQ item anchors unknown claim type {claim!r}",
                    node_id,
                )

    # --- dependency resolution ---------------------------------------------
    for entry in registry.chapters:
        for dependency_id in entry.contract.dependency_ids:
            if dependency_id not in declared_contract_ids:
                severity = "error" if require_complete else "warning"
                add(
                    "dangling_dependency",
                    severity,
                    f"chapters[{entry.node_id}].contract.dependency_ids",
                    f"dependency {dependency_id!r} is not declared by any "
                    f"chapter in this registry",
                    entry.node_id,
                )

    # --- coverage ------------------------------------------------------------
    leaf_union = set(expected_roles)
    cover_node_id = cover_entries[0].node_id if cover_entries else None
    if len(cover_entries) > 1:
        add(
            "duplicate_cover_carrier",
            "error",
            "chapters.coverage_role",
            f"multiple cover carriers declared: "
            f"{sorted(entry.node_id for entry in cover_entries)}",
        )
    if require_complete:
        if not cover_entries:
            add(
                "missing_cover_carrier",
                "error",
                "chapters.coverage_role",
                "the unheaded cover carrier is missing; the leaf union alone is "
                "not full coverage",
            )
        elif not has_front_block:
            add(
                "missing_template_front_block",
                "error",
                "template.node_tree.front_block",
                "registry declares a cover carrier but the template node tree "
                "has no front block",
            )
    expected_cover = expected_cover_id or cover_node_id
    missing_ids = sorted((leaf_union | ({expected_cover} if expected_cover else set())) - set(covered))
    if require_complete:
        for node_id in missing_ids:
            add(
                "missing_coverage",
                "error",
                f"chapters({node_id})",
                "expected carrier has no chapter entry; full mode does not "
                "generate missing chapter data",
                node_id,
            )
    excluded = leaf_union | ({expected_cover} if expected_cover else set())
    unexpected_ids = sorted(set(covered) - excluded)

    heading_leaf_count = sum(1 for role in expected_roles.values() if role == "heading_leaf")
    aggregation_count = sum(
        1 for role in expected_roles.values() if role == "heading_only_aggregation"
    )
    outline_only_count = sum(
        1 for role in expected_roles.values() if role == "outline_only_leaf"
    )
    expected_carrier_count = len(leaf_union) + 1
    expected_set = excluded
    coverage = CoverageSummary(
        heading_leaf_count=heading_leaf_count,
        heading_only_aggregation_count=aggregation_count,
        outline_only_leaf_count=outline_only_count,
        leaf_union_count=len(leaf_union),
        expected_carrier_count=expected_carrier_count,
        covered_carrier_count=len(set(covered) & expected_set),
        cover_node_id=cover_node_id,
        missing_node_ids=tuple(missing_ids),
        unexpected_node_ids=tuple(unexpected_ids),
    )

    if not require_complete:
        add(
            "partial_mode_not_full_acceptance",
            "info",
            "lint.mode",
            "partial batch validation only; the registry is incomplete and "
            "this report never represents full acceptance",
        )

    # One acceptance result for the library and every CLI format. Missing fixture
    # families are allowed during partial authorship, but invalid present fixtures
    # are errors in either mode. No caller flag can disable this verification.
    fixture_results = tuple(check_fixture(registry, fixture) for fixture in registry.fixtures)
    contract_index = _contract_index(registry)
    for fixture, result in zip(registry.fixtures, fixture_results):
        contract = contract_index[fixture.chapter_contract_id]
        if not _fixture_matches(contract, fixture, result):
            add("fixture_expectation_mismatch", "error", f"fixtures[{fixture.fixture_id}]",
                f"{fixture.fixture_kind} fixture produced {result.error_codes()!r}",
                contract.semantic_node_id)
    for entry in registry.chapters:
        kinds = {fixture.fixture_kind for fixture in registry.fixtures
                 if fixture.chapter_contract_id == entry.contract.chapter_contract_id}
        families = ({"positive"}, {"missing_claim", "missing_control"}, {"wrong_source"}, {"skeleton"})
        for family in families:
            if not kinds & family:
                add("missing_fixture", "error" if require_complete else "info",
                    f"chapters[{entry.node_id}].fixtures",
                    f"missing fixture family: {' or '.join(sorted(family))}", entry.node_id)

    no_errors = not any(f.severity == "error" for f in findings)
    status: Literal["complete", "incomplete"]
    if require_complete and no_errors:
        status = "complete"
    else:
        status = "incomplete"
    return LintReport(
        mode="full" if require_complete else "partial",
        status=status,
        findings=tuple(findings),
        coverage=coverage,
        fixture_results=fixture_results,
    )
