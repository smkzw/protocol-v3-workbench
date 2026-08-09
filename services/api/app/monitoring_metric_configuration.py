"""Project-neutral metric configuration candidates for medical monitoring.

This module deliberately stops at an auditable candidate contract.  It does
not infer a metric from a field label, invoke a model, activate a rule, or
claim medical confirmation.  A candidate requires an explicitly declared
metric in a medically confirmed protocol fact and an exact field match in a
frozen full listing field profile.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Iterable, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .monitoring_ai_contracts import content_sha256
from .monitoring_ai_field_profiler import (
    MonitoringFieldProfile,
    MonitoringFieldProfileSnapshot,
)
from .monitoring_protocol_rules import ProtocolFact


METRIC_CONFIGURATION_SCHEMA_VERSION = "monitoring_metric_configuration_v1"
METRIC_DECLARATION_VERSION = "monitoring_metric_declaration_v1"
METRIC_CONFIGURATION_STATUS = "candidate_only"
METRIC_CANDIDATE_STATUS = "pending_medical_confirmation"
METRIC_KINDS = frozenset({"efficacy", "safety"})
METRIC_DIRECTIONS = frozenset(
    {"lower_is_better", "higher_is_better", "stable_range"}
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{1,119}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class MetricConfigurationIssueCode(str, Enum):
    PROTOCOL_FACTS_MISSING = "protocol_facts_missing"
    FACT_NOT_PROTOCOL_FACT = "fact_not_protocol_fact"
    FACT_PROJECT_MISMATCH = "fact_project_mismatch"
    FACT_PROTOCOL_VERSION_MISMATCH = "fact_protocol_version_mismatch"
    UNSUPPORTED_FACT_TYPE = "unsupported_fact_type"
    UNCONFIRMED_PROTOCOL_FACT = "unconfirmed_protocol_fact"
    METRIC_DECLARATIONS_MISSING = "metric_declarations_missing"
    METRIC_DECLARATION_VERSION_UNSUPPORTED = (
        "metric_declaration_version_unsupported"
    )
    METRIC_DECLARATION_INVALID = "metric_declaration_invalid"
    METRIC_KIND_MISMATCH = "metric_kind_mismatch"
    DUPLICATE_METRIC_KEY = "duplicate_metric_key"
    LISTING_PROFILE_INVALID = "listing_profile_invalid"
    LISTING_PROFILE_PROJECT_MISMATCH = "listing_profile_project_mismatch"
    LISTING_FIELD_MISSING = "listing_field_missing"
    LISTING_FIELD_SPARSE = "listing_field_sparse"


def _strict_digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical lowercase SHA-256")
    return value


def _strict_text(value: Any, field_name: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return cleaned


class MetricFieldRef(BaseModel):
    """Exact domain/field reference declared by the protocol fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: StrictStr = Field(min_length=1, max_length=80)
    field: StrictStr = Field(min_length=1, max_length=160)

    @field_validator("domain", "field")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()


class MetricFieldEvidence(BaseModel):
    """Non-identifying field statistics bound to the frozen profile digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: StrictStr = Field(min_length=1, max_length=80)
    field: StrictStr = Field(min_length=1, max_length=160)
    total_rows: StrictInt = Field(ge=0)
    non_empty_count: StrictInt = Field(ge=0)
    null_rate: StrictFloat = Field(ge=0.0, le=1.0)
    inferred_type: StrictStr = Field(min_length=1, max_length=40)

    @field_validator("domain", "field", "inferred_type")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_counts(self) -> "MetricFieldEvidence":
        if self.non_empty_count > self.total_rows:
            raise ValueError("non_empty_count cannot exceed total_rows")
        return self


class MetricConfigurationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: MetricConfigurationIssueCode
    subject: StrictStr = Field(min_length=1, max_length=200)
    detail: StrictStr = Field(min_length=1, max_length=1_000)
    fact_revision_id: StrictStr = ""
    metric_key: StrictStr = ""

    @field_validator("subject", "detail", "fact_revision_id", "metric_key")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()


class MetricConfigurationCandidate(BaseModel):
    """A candidate that still requires an explicit medical-manager decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = METRIC_CONFIGURATION_SCHEMA_VERSION
    declaration_version: str = METRIC_DECLARATION_VERSION
    candidate_id: StrictStr = Field(min_length=2, max_length=160)
    project_id: StrictStr = Field(min_length=2, max_length=160)
    protocol_version_id: StrictStr = Field(min_length=2, max_length=220)
    metric_kind: StrictStr = Field(min_length=2, max_length=40)
    metric_key: StrictStr = Field(min_length=2, max_length=120)
    metric_label: StrictStr = Field(min_length=1, max_length=240)
    unit: StrictStr = Field(default="", max_length=80)
    direction: StrictStr = Field(min_length=2, max_length=40)
    assessment_window: StrictStr = Field(default="", max_length=180)
    fact_revision_id: StrictStr = Field(min_length=2, max_length=220)
    fact_source_entry_id: StrictStr = Field(min_length=2, max_length=200)
    fact_source_locator: StrictStr = Field(min_length=1, max_length=500)
    fact_source_text_sha256: StrictStr
    field_profile_batch_id: StrictStr = Field(min_length=2, max_length=220)
    field_profile_sha256: StrictStr
    field_refs: tuple[MetricFieldRef, ...] = Field(min_length=1, max_length=40)
    field_evidence: tuple[MetricFieldEvidence, ...] = Field(
        min_length=1,
        max_length=40,
    )
    review_flags: tuple[StrictStr, ...] = Field(default=(), max_length=20)
    status: str = METRIC_CANDIDATE_STATUS
    origin: str = "protocol_fact_plus_listing_profile"

    @field_validator("project_id", "protocol_version_id", "metric_key")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("metric_key")
    @classmethod
    def validate_metric_key(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("metric_key must be a stable identifier")
        return value

    @field_validator("metric_kind")
    @classmethod
    def validate_metric_kind(cls, value: str) -> str:
        if value not in METRIC_KINDS:
            raise ValueError("metric_kind is unsupported")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in METRIC_DIRECTIONS:
            raise ValueError("direction is unsupported")
        return value

    @field_validator("fact_source_text_sha256", "field_profile_sha256")
    @classmethod
    def validate_digest(cls, value: str, info) -> str:
        return _strict_digest(value, info.field_name)

    @field_validator("review_flags")
    @classmethod
    def validate_flags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if any(not item for item in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("review_flags must contain unique non-empty values")
        return cleaned

    @model_validator(mode="after")
    def validate_contract(self) -> "MetricConfigurationCandidate":
        if self.schema_version != METRIC_CONFIGURATION_SCHEMA_VERSION:
            raise ValueError("unsupported metric configuration schema version")
        if self.declaration_version != METRIC_DECLARATION_VERSION:
            raise ValueError("unsupported metric declaration version")
        if self.status != METRIC_CANDIDATE_STATUS:
            raise ValueError("metric candidates cannot imply medical confirmation")
        if self.origin != "protocol_fact_plus_listing_profile":
            raise ValueError("unsupported metric candidate origin")
        ref_keys = {(item.domain, item.field) for item in self.field_refs}
        evidence_keys = {(item.domain, item.field) for item in self.field_evidence}
        if ref_keys != evidence_keys:
            raise ValueError("field_refs and field_evidence must cover the same fields")
        identity = self.model_dump(mode="json", exclude={"candidate_id"})
        if content_sha256(identity) != self.candidate_id:
            raise ValueError("metric candidate identity digest drift")
        return self


class MetricConfigurationBundle(BaseModel):
    """Candidate-only output; it is never a release or activation decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = METRIC_CONFIGURATION_SCHEMA_VERSION
    status: str = METRIC_CONFIGURATION_STATUS
    project_id: StrictStr = Field(min_length=2, max_length=160)
    protocol_version_id: StrictStr = Field(min_length=2, max_length=220)
    field_profile_batch_id: StrictStr = ""
    field_profile_sha256: StrictStr = ""
    fact_revision_ids: tuple[StrictStr, ...] = Field(default=(), max_length=200)
    candidates: tuple[MetricConfigurationCandidate, ...] = Field(
        default=(),
        max_length=200,
    )
    issues: tuple[MetricConfigurationIssue, ...] = Field(default=(), max_length=500)
    bundle_sha256: StrictStr

    @field_validator("project_id", "protocol_version_id", "field_profile_batch_id")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("field_profile_sha256", "bundle_sha256")
    @classmethod
    def validate_bundle_digest(cls, value: str, info) -> str:
        if value == "" and info.field_name == "field_profile_sha256":
            return value
        return _strict_digest(value, info.field_name)

    @model_validator(mode="after")
    def validate_bundle(self) -> "MetricConfigurationBundle":
        if self.schema_version != METRIC_CONFIGURATION_SCHEMA_VERSION:
            raise ValueError("unsupported metric configuration schema version")
        if self.status != METRIC_CONFIGURATION_STATUS:
            raise ValueError("metric configuration bundle cannot imply release")
        if self.field_profile_batch_id and not self.field_profile_sha256:
            raise ValueError("field profile batch requires a profile digest")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("metric candidate IDs must be unique")
        issue_keys = tuple(
            (
                item.code.value,
                item.subject,
                item.fact_revision_id,
                item.metric_key,
                item.detail,
            )
            for item in self.issues
        )
        if len(issue_keys) != len(set(issue_keys)):
            raise ValueError("metric configuration issues must be unique")
        identity = self.model_dump(mode="json", exclude={"bundle_sha256"})
        if content_sha256(identity) != self.bundle_sha256:
            raise ValueError("metric configuration bundle digest drift")
        return self

    @property
    def medically_confirmed(self) -> bool:
        return False

    @property
    def usable_candidate_count(self) -> int:
        return sum(not item.review_flags for item in self.candidates)


def build_metric_configuration_candidates(
    *,
    project_id: str,
    protocol_version_id: str,
    facts: Iterable[ProtocolFact],
    field_profile: MonitoringFieldProfileSnapshot | Mapping[str, Any] | None,
) -> MetricConfigurationBundle:
    """Build explicit metric candidates and fail-closed review gaps.

    The protocol fact payload must contain both
    ``metric_configuration_version=monitoring_metric_declaration_v1`` and a
    ``metric_candidates`` list.  The builder never guesses those declarations
    from labels or field names.  A full ``MonitoringFieldProfileSnapshot`` is
    required; the redacted AI payload is intentionally not accepted here.
    """

    project = _strict_text(project_id, "project_id", max_length=160)
    version = _strict_text(protocol_version_id, "protocol_version_id", max_length=220)
    issues: list[MetricConfigurationIssue] = []
    profile, profile_issues = _resolve_profile(
        field_profile,
        project_id=project,
    )
    issues.extend(profile_issues)
    profile_fields: dict[tuple[str, str], MonitoringFieldProfile] = {}
    profile_batch_id = ""
    profile_sha256 = ""
    if profile is not None:
        profile_batch_id = profile.batch_id
        profile_sha256 = profile.profile_sha256
        profile_fields = {
            (item.domain, item.field): item for item in profile.fields
        }

    fact_rows = tuple(facts)
    if not fact_rows:
        issues.append(
            MetricConfigurationIssue(
                code=MetricConfigurationIssueCode.PROTOCOL_FACTS_MISSING,
                subject="protocol_facts",
                detail="at least one protocol fact is required",
            )
        )

    candidates: list[MetricConfigurationCandidate] = []
    fact_revision_ids: list[str] = []
    seen_metric_keys: set[str] = set()
    for fact in fact_rows:
        if not isinstance(fact, ProtocolFact):
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.FACT_NOT_PROTOCOL_FACT,
                    subject=type(fact).__name__,
                    detail="metric configuration requires a source-bound ProtocolFact",
                )
            )
            continue
        fact_revision_ids.append(fact.fact_revision_id)
        if fact.project_id != project:
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.FACT_PROJECT_MISMATCH,
                    subject=fact.fact_revision_id,
                    detail="protocol fact belongs to another project",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        if fact.protocol_version_id != version:
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.FACT_PROTOCOL_VERSION_MISMATCH,
                    subject=fact.fact_revision_id,
                    detail="protocol fact belongs to another protocol version",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        metric_kind = {"efficacy_assessment": "efficacy", "safety_assessment": "safety"}.get(
            fact.fact_type
        )
        if metric_kind is None:
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.UNSUPPORTED_FACT_TYPE,
                    subject=fact.fact_type,
                    detail="only efficacy_assessment and safety_assessment facts can declare metrics",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        if fact.status != "medically_confirmed":
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.UNCONFIRMED_PROTOCOL_FACT,
                    subject=fact.fact_revision_id,
                    detail="metric candidates require a medically_confirmed protocol fact",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        payload = fact.normalized_payload
        declaration_version = payload.get("metric_configuration_version")
        declarations = payload.get("metric_candidates")
        if declarations is None:
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.METRIC_DECLARATIONS_MISSING,
                    subject=fact.fact_revision_id,
                    detail="fact has no explicit metric_candidates declaration",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        if declaration_version != METRIC_DECLARATION_VERSION:
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.METRIC_DECLARATION_VERSION_UNSUPPORTED,
                    subject=fact.fact_revision_id,
                    detail="metric declaration version is missing or unsupported",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        if not isinstance(declarations, Sequence) or isinstance(
            declarations,
            (str, bytes, bytearray),
        ):
            issues.append(
                MetricConfigurationIssue(
                    code=MetricConfigurationIssueCode.METRIC_DECLARATION_INVALID,
                    subject=fact.fact_revision_id,
                    detail="metric_candidates must be a sequence of objects",
                    fact_revision_id=fact.fact_revision_id,
                )
            )
            continue
        for raw_declaration in declarations:
            try:
                declaration = _parse_declaration(raw_declaration)
            except ValueError as exc:
                issues.append(
                    MetricConfigurationIssue(
                        code=MetricConfigurationIssueCode.METRIC_DECLARATION_INVALID,
                        subject=fact.fact_revision_id,
                        detail=str(exc),
                        fact_revision_id=fact.fact_revision_id,
                    )
                )
                continue
            metric_key = declaration["metric_key"]
            if declaration["metric_kind"] != metric_kind:
                issues.append(
                    MetricConfigurationIssue(
                        code=MetricConfigurationIssueCode.METRIC_KIND_MISMATCH,
                        subject=metric_key,
                        detail="metric_kind must agree with the protocol fact type",
                        fact_revision_id=fact.fact_revision_id,
                        metric_key=metric_key,
                    )
                )
                continue
            if metric_key in seen_metric_keys:
                issues.append(
                    MetricConfigurationIssue(
                        code=MetricConfigurationIssueCode.DUPLICATE_METRIC_KEY,
                        subject=metric_key,
                        detail="metric_key is declared more than once for this project/version",
                        fact_revision_id=fact.fact_revision_id,
                        metric_key=metric_key,
                    )
                )
                continue
            refs = tuple(declaration["field_refs"])
            missing = [
                ref
                for ref in refs
                if (ref.domain, ref.field) not in profile_fields
            ]
            if missing:
                issues.append(
                    MetricConfigurationIssue(
                        code=MetricConfigurationIssueCode.LISTING_FIELD_MISSING,
                        subject=metric_key,
                        detail="listing field declaration has no exact frozen-profile match: "
                        + ", ".join(f"{item.domain}.{item.field}" for item in missing),
                        fact_revision_id=fact.fact_revision_id,
                        metric_key=metric_key,
                    )
                )
                continue
            evidence = tuple(
                _field_evidence(profile_fields[(ref.domain, ref.field)])
                for ref in refs
            )
            review_flags = tuple(
                sorted(
                    {
                        "sparse_listing_field"
                        for item in evidence
                        if item.total_rows == 0
                        or item.non_empty_count == 0
                        or item.null_rate >= 1.0
                    }
                )
            )
            if review_flags:
                issues.append(
                    MetricConfigurationIssue(
                        code=MetricConfigurationIssueCode.LISTING_FIELD_SPARSE,
                        subject=metric_key,
                        detail="exact listing field exists but has no usable observed values; medical review is required",
                        fact_revision_id=fact.fact_revision_id,
                        metric_key=metric_key,
                    )
                )
            candidate_identity = {
                "schema_version": METRIC_CONFIGURATION_SCHEMA_VERSION,
                "declaration_version": METRIC_DECLARATION_VERSION,
                "project_id": project,
                "protocol_version_id": version,
                "metric_kind": metric_kind,
                "metric_key": metric_key,
                "metric_label": declaration["metric_label"],
                "unit": declaration["unit"],
                "direction": declaration["direction"],
                "assessment_window": declaration["assessment_window"],
                "fact_revision_id": fact.fact_revision_id,
                "fact_source_entry_id": fact.source_entry_id,
                "fact_source_locator": fact.source_locator,
                "fact_source_text_sha256": fact.source_text_sha256,
                "field_profile_batch_id": profile_batch_id,
                "field_profile_sha256": profile_sha256,
                "field_refs": [item.model_dump(mode="json") for item in refs],
                "field_evidence": [item.model_dump(mode="json") for item in evidence],
                "review_flags": list(review_flags),
                "status": METRIC_CANDIDATE_STATUS,
                "origin": "protocol_fact_plus_listing_profile",
            }
            candidate = MetricConfigurationCandidate(
                candidate_id=content_sha256(candidate_identity),
                **candidate_identity,
            )
            candidates.append(candidate)
            seen_metric_keys.add(metric_key)

    candidates.sort(key=lambda item: item.candidate_id)
    issues.sort(
        key=lambda item: (
            item.code.value,
            item.subject,
            item.fact_revision_id,
            item.metric_key,
        )
    )
    bundle_identity = {
        "schema_version": METRIC_CONFIGURATION_SCHEMA_VERSION,
        "status": METRIC_CONFIGURATION_STATUS,
        "project_id": project,
        "protocol_version_id": version,
        "field_profile_batch_id": profile_batch_id,
        "field_profile_sha256": profile_sha256,
        "fact_revision_ids": sorted(set(fact_revision_ids)),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "issues": [item.model_dump(mode="json") for item in issues],
    }
    return MetricConfigurationBundle(
        bundle_sha256=content_sha256(bundle_identity),
        **bundle_identity,
    )


def _resolve_profile(
    profile: MonitoringFieldProfileSnapshot | Mapping[str, Any] | None,
    *,
    project_id: str,
) -> tuple[MonitoringFieldProfileSnapshot | None, tuple[MetricConfigurationIssue, ...]]:
    if profile is None:
        return None, (
            MetricConfigurationIssue(
                code=MetricConfigurationIssueCode.LISTING_PROFILE_INVALID,
                subject="field_profile",
                detail="a complete frozen MonitoringFieldProfileSnapshot is required",
            ),
        )
    try:
        if isinstance(profile, MonitoringFieldProfileSnapshot):
            resolved = profile
        elif isinstance(profile, Mapping):
            resolved = MonitoringFieldProfileSnapshot.from_dict(profile)
        else:
            raise ValueError("field_profile must be a complete snapshot or mapping")
    except (TypeError, ValueError, KeyError) as exc:
        return None, (
            MetricConfigurationIssue(
                code=MetricConfigurationIssueCode.LISTING_PROFILE_INVALID,
                subject="field_profile",
                detail=str(exc),
            ),
        )
    if resolved.project_id != project_id:
        return None, (
            MetricConfigurationIssue(
                code=MetricConfigurationIssueCode.LISTING_PROFILE_PROJECT_MISMATCH,
                subject=resolved.batch_id,
                detail="listing field profile belongs to another project",
            ),
        )
    return resolved, ()


def _parse_declaration(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("each metric declaration must be an object")
    allowed = {
        "metric_kind",
        "metric_key",
        "metric_label",
        "unit",
        "direction",
        "assessment_window",
        "field_refs",
    }
    if set(raw) != allowed:
        raise ValueError("metric declaration has unexpected or missing fields")
    metric_kind = _strict_text(raw["metric_kind"], "metric_kind", max_length=40)
    metric_key = _strict_text(raw["metric_key"], "metric_key", max_length=120)
    if not _IDENTIFIER_RE.fullmatch(metric_key):
        raise ValueError("metric_key must be a stable identifier")
    metric_label = _strict_text(raw["metric_label"], "metric_label", max_length=240)
    unit = raw["unit"]
    if not isinstance(unit, str):
        raise ValueError("unit must be a string")
    unit = unit.strip()
    direction = _strict_text(raw["direction"], "direction", max_length=40)
    if direction not in METRIC_DIRECTIONS:
        raise ValueError("direction is unsupported")
    assessment_window = raw["assessment_window"]
    if not isinstance(assessment_window, str):
        raise ValueError("assessment_window must be a string")
    assessment_window = assessment_window.strip()
    raw_refs = raw["field_refs"]
    if not isinstance(raw_refs, Sequence) or isinstance(
        raw_refs,
        (str, bytes, bytearray),
    ) or not raw_refs:
        raise ValueError("field_refs must be a non-empty sequence")
    refs = tuple(MetricFieldRef.model_validate(item) for item in raw_refs)
    if len({(item.domain, item.field) for item in refs}) != len(refs):
        raise ValueError("field_refs must be unique")
    return {
        "metric_kind": metric_kind,
        "metric_key": metric_key,
        "metric_label": metric_label,
        "unit": unit,
        "direction": direction,
        "assessment_window": assessment_window,
        "field_refs": refs,
    }


def _field_evidence(field: MonitoringFieldProfile) -> MetricFieldEvidence:
    return MetricFieldEvidence(
        domain=field.domain,
        field=field.field,
        total_rows=field.total_rows,
        non_empty_count=field.non_empty_count,
        null_rate=field.null_rate,
        inferred_type=field.inferred_type,
    )


__all__ = [
    "METRIC_CANDIDATE_STATUS",
    "METRIC_CONFIGURATION_SCHEMA_VERSION",
    "METRIC_CONFIGURATION_STATUS",
    "METRIC_DECLARATION_VERSION",
    "MetricConfigurationBundle",
    "MetricConfigurationCandidate",
    "MetricConfigurationIssue",
    "MetricConfigurationIssueCode",
    "MetricFieldEvidence",
    "MetricFieldRef",
    "build_metric_configuration_candidates",
]
