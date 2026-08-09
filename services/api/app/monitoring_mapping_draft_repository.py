from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiInputRevision,
    MonitoringAiJobStatus,
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
)
from .monitoring_mapping_contract import (
    MonitoringFieldKind,
    validate_monitoring_mapping_semantics,
)
from .monitoring_mapping_semantic_quality import (
    MappingSemanticQualityReport,
    SemanticQualityStatus,
    evaluate_mapping_semantic_quality,
    resolve_closed_monitoring_role_concept,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_EDITABLE_FIELD_KEYS = frozenset(
    {
        "recommended_role",
        "field_kind",
        "confidence",
        "uncertainty",
        "user_action",
        "related_fields",
        "standards_reference",
        "derivation_lineage",
        "value_constraints",
    }
)
_PARTIAL_DATE_VALUE_RE = re.compile(
    r"^(?:\d{4}(?:[-/.](?:UK|UNK|UNKNOWN|XX|00)){1,2}"
    r"|\d{4}[-/.]\d{1,2}[-/.](?:UK|UNK|UNKNOWN|XX|00)"
    r"|\d{4}[-/.](?:UK|UNK|UNKNOWN|XX|00)[-/.]\d{1,2}"
    r"|\d{4}[-/.]\d{1,2}|\d{4})$",
    re.IGNORECASE,
)
_LOW_CONFIDENCE_UNRESOLVED_ROLE_THRESHOLD = 0.70

# Project-neutral IP action families. The authoritative marker table lives in
# monitoring_mapping_semantic_quality._ACTION_MARKERS; this local copy keeps the
# assembly boundary readable without coupling to a private module symbol.
_IP_ACTION_MARKERS: Mapping[str, tuple[str, ...]] = {
    "ip.administration": (
        "administration",
        "administered.dose",
        "actual.dose",
        "actual.exposure",
        "实际给药",
    ),
    "ip.dose_adjustment": ("dose.adjustment", "dose.change", "剂量调整"),
    "ip.interruption": ("interruption", "temporary.discontinuation", "暂时停药"),
    "ip.discontinuation": ("permanent.discontinuation", "永久停药"),
    "ip.restart": ("restart", "resume", "重启"),
    "ip.dispense": ("dispense", "dispensing", "发放"),
    "ip.return": ("return", "returned", "回收"),
    "ip.compliance": ("compliance", "adherence", "依从"),
}

# Closed generic source-value role used when a role merges several IP action
# families: the assembled field keeps its source value but can never become a
# single-action capability input.
_MULTI_ACTION_QUARANTINE_ROLE = "clinical.source_other"
_MULTI_ACTION_QUARANTINE_ACTION = "multi_action_ip_quarantined"
_INCOMPLETE_CODING_DOWNGRADE_ACTION = (
    "incomplete_coding_downgraded_to_source_collected"
)
_CODING_SUPPORT_ROLE_CONCEPT_IDS = frozenset(
    {
        "coding.meddra.dictionary_version",
        "coding.meddra.dictionary_language",
        "coding.drug.dictionary_version",
        "coding.drug.dictionary_language",
    }
)
_NON_SPECIFIC_CODING_SYSTEM_RE = re.compile(
    r"(?:unknown|unspecified|pending|field.?name|term.?code|"
    r"project.?dictionary|local.?dictionary|待确认|未指定|不明确|不详|"
    r"项目(?:字典|词典)|本地(?:字典|词典)|未明确(?:的)?(?:项目)?(?:字典|词典))",
    re.IGNORECASE,
)


class MonitoringMappingDraftError(ValueError):
    pass


class MonitoringMappingSourceStateError(MonitoringMappingDraftError):
    pass


class MonitoringMappingStateConflictError(MonitoringMappingDraftError):
    pass


class MonitoringMappingNotFoundError(MonitoringMappingDraftError):
    pass


class MonitoringMappingDraftStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class MonitoringMappingField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=240)
    recommended_role: str = Field(min_length=2, max_length=240)
    field_kind: MonitoringFieldKind
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(min_length=1, max_length=4_000)
    user_action: str = Field(min_length=1, max_length=2_000)
    related_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    standards_reference: Optional[dict[str, Any]] = None
    derivation_lineage: Optional[dict[str, Any]] = None
    value_constraints: Optional[dict[str, Any]] = None
    object_identity: Literal[
        "not_applicable",
        "unresolved",
        "investigational_product",
        "placebo",
        "active_comparator",
        "background_therapy",
        "rescue_therapy",
        "concomitant_non_ip",
        "other_non_ip_treatment",
    ] = "not_applicable"
    object_identity_evidence_fields: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=24,
    )
    object_identity_binding_id: str = Field(default="", max_length=160)
    validated_treatment_identity_binding: Optional[dict[str, Any]] = None
    dose_semantics: Literal[
        "not_applicable",
        "unresolved",
        "planned",
        "prescribed",
        "actual_administered",
        "dispensed",
        "returned",
        "duplicate_or_derived",
    ] = "not_applicable"
    quality_gate_actions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=24,
    )

    @field_validator("domain", "source_field", "recommended_role")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator(
        "related_fields",
        "evidence_ids",
        "object_identity_evidence_fields",
        "quality_gate_actions",
    )
    @classmethod
    def validate_unique_text(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("field list values must be non-empty and unique")
        return cleaned

    @model_validator(mode="after")
    def validate_mapping_boundary(self) -> "MonitoringMappingField":
        validate_monitoring_mapping_semantics(
            domain=self.domain,
            source_field=self.source_field,
            recommended_role=self.recommended_role,
            field_kind=self.field_kind,
            standards_reference=self.standards_reference,
            derivation_lineage=self.derivation_lineage,
        )
        if self.value_constraints is not None:
            precision = str(
                self.value_constraints.get("date_precision") or ""
            ).strip()
            if precision not in {"year", "month", "day", "partial", "mixed"}:
                raise ValueError("value_constraints.date_precision is invalid")
            exact = self.value_constraints.get("supports_exact_date")
            if not isinstance(exact, bool):
                raise ValueError(
                    "value_constraints.supports_exact_date must be boolean"
                )
        if self.validated_treatment_identity_binding is not None:
            binding = self.validated_treatment_identity_binding
            required = {
                "schema_version",
                "binding_id",
                "source_domain",
                "source_field",
                "target_domain",
                "relationship_type",
                "join_keys",
            }
            if (
                set(binding) != required
                or binding.get("schema_version")
                != "monitoring_treatment_identity_binding_v1"
                or str(binding.get("binding_id", "")).strip()
                != self.object_identity_binding_id
                or str(binding.get("target_domain", "")).strip().casefold()
                != self.domain.casefold()
                or not isinstance(binding.get("join_keys"), list)
                or not binding["join_keys"]
            ):
                raise ValueError(
                    "validated treatment identity binding is inconsistent"
                )
        return self


class MonitoringMappingFieldSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    source_field: str
    job_id: str
    candidate_id: str
    candidate_content_sha256: str
    input_revision_sha256: str
    prompt_version: str
    evidence_ids: tuple[str, ...]

    @field_validator("candidate_content_sha256", "input_revision_sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        return _require_sha256(value, "field source hash")


class MonitoringMappingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: str
    project_id: str
    batch_id: str
    full_profile_sha256: str
    full_input_sha256: str
    input_revision: MonitoringAiInputRevision
    input_revision_sha256: str
    source_set_sha256: str
    status: MonitoringMappingDraftStatus
    version: int
    fields: tuple[MonitoringMappingField, ...]
    field_sources: tuple[MonitoringMappingFieldSource, ...]
    expected_job_ids: tuple[str, ...]
    confirmed_revision_id: str = ""
    created_at: datetime
    updated_at: datetime


class MonitoringMappingRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_revision: str
    draft_id: str
    project_id: str
    batch_id: str
    full_profile_sha256: str
    full_input_sha256: str
    input_revision_sha256: str
    source_set_sha256: str
    draft_version: int
    fields: tuple[MonitoringMappingField, ...]
    field_sources: tuple[MonitoringMappingFieldSource, ...]
    semantic_quality_report: dict[str, Any] = Field(default_factory=dict)
    semantic_quality_report_sha256: str = ""
    confirmed_by: str
    confirmation_reason: str
    created_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _require_safe_identifier(value: str, label: str) -> str:
    cleaned = value.strip()
    if not _SAFE_ID_RE.fullmatch(cleaned):
        raise ValueError(f"{label} contains unsupported characters")
    return cleaned


def _require_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _model_sequence_json(values: Any) -> str:
    return canonical_json(
        [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in values
        ]
    )


def _mapping_draft_id(
    *,
    project_id: str,
    batch_id: str,
    full_profile_sha256: str,
    input_revision_sha256: str,
    source_set_sha256: str,
) -> str:
    """Return the existing immutable assembly-anchor identity for a draft."""

    return "monmapdraft_" + content_sha256(
        {
            "project_id": project_id,
            "batch_id": batch_id,
            "full_profile_sha256": full_profile_sha256,
            "input_revision_sha256": input_revision_sha256,
            "source_set_sha256": source_set_sha256,
        }
    )[:28]


_MEDDRA_ANCHOR_SCHEMA_VERSION = "monitoring_meddra_source_anchor_v1"


def _anchor_complete_meddra_source_chains(
    fields: list[MonitoringMappingField],
    field_sources: list[MonitoringMappingFieldSource],
    *,
    input_revision_sha256: str,
    source_set_sha256: str,
    expected_job_ids: tuple[str, ...],
) -> list[MonitoringMappingField]:
    """Add only source-set-proven reported-term anchors to closed MedDRA chains."""

    field_pairs = {(item.domain, item.source_field) for item in fields}
    source_pairs = {
        (item.domain, item.source_field) for item in field_sources
    }
    normalized_field_pairs = {
        (domain.casefold(), source_field.casefold())
        for domain, source_field in field_pairs
    }
    normalized_source_pairs = {
        (domain.casefold(), source_field.casefold())
        for domain, source_field in source_pairs
    }
    if (
        field_pairs != source_pairs
        or normalized_field_pairs != normalized_source_pairs
        or len(normalized_field_pairs) != len(fields)
    ):
        return fields
    expected_jobs = set(expected_job_ids)
    if not expected_jobs or any(
        item.input_revision_sha256 != input_revision_sha256
        or item.job_id not in expected_jobs
        for item in field_sources
    ):
        return fields

    fields_by_domain: dict[str, list[tuple[int, MonitoringMappingField]]] = {}
    for index, field in enumerate(fields):
        domain_key = field.domain.casefold()
        if domain_key in {"ae", "mh"}:
            fields_by_domain.setdefault(domain_key, []).append((index, field))

    anchored = list(fields)
    for domain_key, domain_fields in fields_by_domain.items():
        expected_report_role = (
            "ae.verbatim_term"
            if domain_key == "ae"
            else "mh.verbatim_term"
        )
        reported_terms: list[MonitoringMappingField] = []
        version_fields: dict[str, MonitoringMappingField] = {}
        standardized_fields: list[tuple[int, MonitoringMappingField]] = []
        available = {
            field.source_field.casefold(): field
            for _, field in domain_fields
        }
        for index, field in domain_fields:
            concept = resolve_closed_monitoring_role_concept(
                field.recommended_role
            )
            if concept is None:
                continue
            if (
                concept.role_concept_id == expected_report_role
                and field.field_kind == MonitoringFieldKind.SOURCE_COLLECTED
            ):
                reported_terms.append(field)
            elif (
                concept.role_concept_id
                == "coding.meddra.dictionary_version"
                and field.field_kind == MonitoringFieldKind.SOURCE_METADATA
            ):
                version_fields[field.source_field.casefold()] = field
            elif (
                concept.role_family == "coding.meddra"
                and concept.value_semantics in {"code", "term"}
                and field.field_kind
                == MonitoringFieldKind.STANDARDIZED_CODED
            ):
                standardized_fields.append((index, field))

        if not reported_terms or not version_fields or not standardized_fields:
            continue

        pending: list[
            tuple[
                int,
                MonitoringMappingField,
                dict[str, Any],
                MonitoringMappingField,
            ]
        ] = []
        chain_is_closed = True
        for index, field in standardized_fields:
            lineage = dict(field.derivation_lineage or {})
            source_fields = lineage.get("source_fields")
            version_name = str(
                lineage.get("dictionary_version_field") or ""
            ).strip()
            coding_system = str(
                lineage.get("coding_system") or ""
            ).strip()
            version_field = version_fields.get(version_name.casefold())
            if (
                coding_system.casefold() != "meddra"
                or version_field is None
                or version_field.source_field.casefold()
                == field.source_field.casefold()
                or not isinstance(source_fields, (list, tuple))
                or not source_fields
                or any(
                    not str(source).strip()
                    or str(source).strip().casefold() not in available
                    for source in source_fields
                )
            ):
                chain_is_closed = False
                break
            pending.append((index, field, lineage, version_field))
        if not chain_is_closed:
            continue

        report_names = tuple(
            sorted(
                (item.source_field for item in reported_terms),
                key=str.casefold,
            )
        )
        for index, field, lineage, version_field in pending:
            source_fields = [
                str(item).strip()
                for item in lineage["source_fields"]
                if str(item).strip()
            ]
            seen = {item.casefold() for item in source_fields}
            for report_name in report_names:
                if report_name.casefold() not in seen:
                    source_fields.append(report_name)
                    seen.add(report_name.casefold())
            lineage["source_fields"] = source_fields
            lineage["source_anchor_contract"] = {
                "schema_version": _MEDDRA_ANCHOR_SCHEMA_VERSION,
                "anchor_type": "reported_term_to_standardized_meddra",
                "scope": (
                    "same_project_same_domain_complete_frozen_source_set"
                ),
                "domain": field.domain,
                "reported_term_fields": list(report_names),
                "dictionary_version_field": version_field.source_field,
                "input_revision_sha256": input_revision_sha256,
                "source_set_sha256": source_set_sha256,
            }
            anchored[index] = field.model_copy(
                update={"derivation_lineage": lineage}
            )
    return anchored


def _quarantine_low_confidence_unresolved_role(
    field: MonitoringMappingField,
) -> MonitoringMappingField:
    """Keep uncertain source semantics visible without blocking the whole map."""

    if (
        field.field_kind != MonitoringFieldKind.SOURCE_COLLECTED
        or field.confidence >= _LOW_CONFIDENCE_UNRESOLVED_ROLE_THRESHOLD
        or resolve_closed_monitoring_role_concept(field.recommended_role)
        is not None
    ):
        return field

    quality = evaluate_mapping_semantic_quality(fields=(field,))
    global_rules = {
        item.rule_id
        for item in quality.finding_groups
        if item.severity.value == "global_blocker"
    }
    if global_rules != {"G-ROLE-002"}:
        return field

    return field.model_copy(
        update={"field_kind": MonitoringFieldKind.UNMAPPED}
    )


def _normalize_known_export_context(
    field: MonitoringMappingField,
) -> MonitoringMappingField:
    """Normalize exporter context fields without interpreting clinical values."""

    if field.field_kind not in {
        MonitoringFieldKind.SOURCE_COLLECTED,
        MonitoringFieldKind.SOURCE_METADATA,
    }:
        return field
    source_field = field.source_field.strip().upper()
    normalized: tuple[str, str] | None = None
    if source_field == "FORM":
        normalized = ("form_name", "EDC 导出表单显示名称")
    elif source_field == "PAGE":
        normalized = ("page_name", "EDC 导出页面显示名称")
    elif source_field == "LINE":
        normalized = ("record_line_number", "EDC 导出记录行序号")
    elif source_field == "LBNAM" and field.domain.strip().upper().startswith(
        "LB"
    ):
        normalized = (
            "laboratory_configuration_name",
            "项目实验室检查配置或面板显示名称",
        )
    if normalized is None:
        return field

    role, description = normalized
    note = (
        f"系统按跨域稳定导出上下文归一为{description}；"
        "原独立 AI 判断保留在候选审计记录中。"
    )
    uncertainty = field.uncertainty.strip()
    return field.model_copy(
        update={
            "recommended_role": role,
            "field_kind": MonitoringFieldKind.SOURCE_METADATA,
            "uncertainty": f"{note}{uncertainty}" if uncertainty else note,
            "user_action": (
                "若项目数据字典将该字段定义为受试者级临床采集值，"
                "请在正式确认前修订。"
            ),
        }
    )


def _normalize_known_coding_support_metadata(
    field: MonitoringMappingField,
) -> MonitoringMappingField:
    """Close explicit dictionary support roles as non-clinical metadata.

    The immutable AI candidate remains unchanged. Draft assembly only closes
    a role the provider already identified as a dictionary version/language;
    it does not infer a coding system from a field name or value.
    """

    if field.field_kind not in {
        MonitoringFieldKind.SOURCE_COLLECTED,
        MonitoringFieldKind.SOURCE_METADATA,
    }:
        return field
    concept = resolve_closed_monitoring_role_concept(field.recommended_role)
    if concept is None or concept.role_concept_id not in {
        "coding.meddra.dictionary_version",
        "coding.meddra.dictionary_language",
        "coding.drug.dictionary_version",
        "coding.drug.dictionary_language",
    }:
        return field
    if field.field_kind == MonitoringFieldKind.SOURCE_METADATA:
        return field

    note = (
        "系统按独立 AI 已明确声明的词典版本/语言支持角色，将该字段"
        "确定性归一为来源元数据；原候选字段性质保留在候选审计记录中。"
    )
    uncertainty = field.uncertainty.strip()
    actions = tuple(
        dict.fromkeys(
            (*field.quality_gate_actions, "coding_support_metadata_closed")
        )
    )
    return field.model_copy(
        update={
            "field_kind": MonitoringFieldKind.SOURCE_METADATA,
            "uncertainty": f"{note}{uncertainty}" if uncertainty else note,
            "user_action": (
                "请结合项目数据字典确认该词典版本或语言字段；"
                "正式编码血缘仍须同时满足来源术语/代码及独立版本字段合同。"
            ),
            "quality_gate_actions": actions,
        }
    )


def _normalize_action_token(value: str) -> str:
    return re.sub(r"[\s_:/\\-]+", ".", str(value).strip().casefold()).strip(".")


def _quarantine_multi_action_ip_role(
    field: MonitoringMappingField,
) -> MonitoringMappingField:
    """Block action-specific use of roles that merge multiple IP action families.

    The immutable AI candidate is never rewritten. Draft assembly replaces an
    ambiguous multi-action role with a closed generic source-value role so that
    no single administration/compliance/return capability can become ready from
    this assembled field, and records an explicit quarantine action.
    """

    if field.field_kind == MonitoringFieldKind.UNMAPPED:
        return field
    token = _normalize_action_token(field.recommended_role)
    matched = tuple(
        sorted(
            family
            for family, markers in _IP_ACTION_MARKERS.items()
            if any(marker in token for marker in markers)
        )
    )
    if len(matched) <= 1:
        return field
    note = (
        "系统按独立 AI 已声明的角色文本核验到多个试验药物动作族"
        f"（{'、'.join(matched)}）；该角色不得被解析为任一单一动作，"
        "草稿装配将该字段隔离为项目无关的闭合来源值角色，并禁止其"
        "参与给药、回收、依从性等任何单一动作结论。"
    )
    uncertainty = field.uncertainty.strip()
    actions = tuple(
        dict.fromkeys(
            (*field.quality_gate_actions, _MULTI_ACTION_QUARANTINE_ACTION)
        )
    )
    return field.model_copy(
        update={
            "recommended_role": _MULTI_ACTION_QUARANTINE_ROLE,
            "field_kind": MonitoringFieldKind.SOURCE_COLLECTED,
            "uncertainty": f"{note}{uncertainty}" if uncertainty else note,
            "user_action": (
                "请结合项目数据字典将不同试验药物动作拆分为独立字段；"
                "在拆分前，该字段仅保留来源值语义，不得用于任何单一"
                "试验药物动作结论。"
            ),
            "quality_gate_actions": actions,
        }
    )


def _standardized_coding_lineage_is_complete(
    field: MonitoringMappingField,
    available: Mapping[str, MonitoringMappingField],
) -> bool:
    """Verify one standardized claim against the assembled same-domain set.

    A claim is complete only when its explicit lineage names a non-generic
    coding system, real same-domain source fields (never the field itself) and
    a separate declared dictionary-version support field that is already a
    closed source-metadata role in the same assembled domain.
    """

    lineage = field.derivation_lineage or {}
    coding_system = str(lineage.get("coding_system") or "").strip()
    source_fields = lineage.get("source_fields")
    version_name = str(lineage.get("dictionary_version_field") or "").strip()
    if (
        not coding_system
        or _NON_SPECIFIC_CODING_SYSTEM_RE.search(coding_system)
        or not isinstance(source_fields, (list, tuple))
        or not source_fields
        or any(
            not str(source).strip()
            or str(source).strip().casefold() == field.source_field.casefold()
            or str(source).strip().casefold() not in available
            for source in source_fields
        )
        or not version_name
        or version_name.casefold() == field.source_field.casefold()
    ):
        return False
    version_field = available.get(version_name.casefold())
    if version_field is None:
        return False
    concept = resolve_closed_monitoring_role_concept(
        version_field.recommended_role
    )
    return (
        concept is not None
        and concept.role_concept_id in _CODING_SUPPORT_ROLE_CONCEPT_IDS
        and version_field.field_kind == MonitoringFieldKind.SOURCE_METADATA
    )


def _downgrade_unverifiable_standardized_coding(
    fields: list[MonitoringMappingField],
) -> list[MonitoringMappingField]:
    """Fail-closed whole-source-set downgrade of unverifiable coding claims.

    Runs after MedDRA anchoring. Any standardized_coded field whose explicit
    lineage does not verify against the complete assembled same-domain source
    set is downgraded to source_collected. Coding system, version and lineage
    are never invented; the immutable candidate keeps its original claim.
    """

    by_domain: dict[str, list[tuple[int, MonitoringMappingField]]] = {}
    for index, field in enumerate(fields):
        by_domain.setdefault(field.domain.casefold(), []).append((index, field))
    downgraded = list(fields)
    for domain_fields in by_domain.values():
        available = {
            field.source_field.casefold(): field for _, field in domain_fields
        }
        for index, field in domain_fields:
            if field.field_kind != MonitoringFieldKind.STANDARDIZED_CODED:
                continue
            if _standardized_coding_lineage_is_complete(field, available):
                continue
            note = (
                "系统按完整来源集核验，该标准编码声明的血缘无法闭合"
                "（缺少非泛指编码体系、真实同域来源字段，或独立声明的"
                "词典版本元数据字段），已确定性降级为来源值；"
                "原候选编码声明及血缘保留在不可变候选审计记录中。"
            )
            uncertainty = field.uncertainty.strip()
            actions = tuple(
                dict.fromkeys(
                    (
                        *field.quality_gate_actions,
                        _INCOMPLETE_CODING_DOWNGRADE_ACTION,
                    )
                )
            )
            downgraded[index] = field.model_copy(
                update={
                    "field_kind": MonitoringFieldKind.SOURCE_COLLECTED,
                    # A source-collected assembled field must not carry a
                    # derivation lineage (contract); the immutable candidate
                    # keeps the original standardized claim byte-for-byte.
                    "derivation_lineage": None,
                    "uncertainty": (
                        f"{note}{uncertainty}" if uncertainty else note
                    ),
                    "user_action": (
                        "请结合项目数据字典补齐可核验编码血缘"
                        "（编码体系、真实来源字段、独立词典版本字段），"
                        "或保持来源值语义。"
                    ),
                    "quality_gate_actions": actions,
                }
            )
    return downgraded


class MonitoringMappingDraftRepository:
    """Durable assembly boundary between accepted AI output and formal mapping."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_mapping_drafts (
                    draft_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    full_profile_sha256 TEXT NOT NULL,
                    full_input_sha256 TEXT NOT NULL,
                    input_revision_json TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    source_set_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    fields_json TEXT NOT NULL,
                    expected_job_ids_json TEXT NOT NULL,
                    confirmed_revision_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, batch_id, full_profile_sha256)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_field_sources (
                    draft_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    source_field TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    candidate_content_sha256 TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    PRIMARY KEY(draft_id, domain, source_field),
                    FOREIGN KEY(draft_id)
                        REFERENCES monitoring_mapping_drafts(draft_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_edit_operations (
                    operation_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_version INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(draft_id)
                        REFERENCES monitoring_mapping_drafts(draft_id),
                    PRIMARY KEY(project_id, operation_id),
                    UNIQUE(draft_id, operation_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_revisions (
                    mapping_revision TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    full_profile_sha256 TEXT NOT NULL,
                    full_input_sha256 TEXT NOT NULL,
                    input_revision_sha256 TEXT NOT NULL,
                    source_set_sha256 TEXT NOT NULL,
                    draft_version INTEGER NOT NULL,
                    fields_json TEXT NOT NULL,
                    field_sources_json TEXT NOT NULL,
                    semantic_quality_report_json TEXT NOT NULL DEFAULT '{}',
                    semantic_quality_report_sha256 TEXT NOT NULL DEFAULT '',
                    confirmed_by TEXT NOT NULL,
                    confirmation_reason TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    confirmation_request_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS idx_monitoring_mapping_drafts_project
                ON monitoring_mapping_drafts(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_monitoring_mapping_sources_project
                ON monitoring_mapping_field_sources(project_id, draft_id);
                CREATE INDEX IF NOT EXISTS idx_monitoring_mapping_revisions_project
                ON monitoring_mapping_revisions(project_id, created_at);

                CREATE TRIGGER IF NOT EXISTS trg_mapping_confirmed_draft_no_update
                BEFORE UPDATE ON monitoring_mapping_drafts
                WHEN OLD.status = 'confirmed'
                BEGIN
                    SELECT RAISE(ABORT, 'confirmed mapping draft is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_mapping_draft_no_delete
                BEFORE DELETE ON monitoring_mapping_drafts
                BEGIN
                    SELECT RAISE(ABORT, 'mapping draft deletion is forbidden');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_mapping_sources_no_update
                BEFORE UPDATE ON monitoring_mapping_field_sources
                BEGIN
                    SELECT RAISE(ABORT, 'mapping source lineage is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_mapping_sources_no_delete
                BEFORE DELETE ON monitoring_mapping_field_sources
                BEGIN
                    SELECT RAISE(ABORT, 'mapping source lineage deletion is forbidden');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_mapping_revision_no_update
                BEFORE UPDATE ON monitoring_mapping_revisions
                BEGIN
                    SELECT RAISE(ABORT, 'mapping revision is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_mapping_revision_no_delete
                BEFORE DELETE ON monitoring_mapping_revisions
                BEGIN
                    SELECT RAISE(ABORT, 'mapping revision deletion is forbidden');
                END;
                """
            )
            revision_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_mapping_revisions)"
                ).fetchall()
            }
            if "semantic_quality_report_json" not in revision_columns:
                connection.execute(
                    """
                    ALTER TABLE monitoring_mapping_revisions
                    ADD COLUMN semantic_quality_report_json
                    TEXT NOT NULL DEFAULT '{}'
                    """
                )
            if "semantic_quality_report_sha256" not in revision_columns:
                connection.execute(
                    """
                    ALTER TABLE monitoring_mapping_revisions
                    ADD COLUMN semantic_quality_report_sha256
                    TEXT NOT NULL DEFAULT ''
                    """
                )
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("monitoring mapping repository integrity check failed")

    def assemble(
        self,
        project_id: str,
        batch_id: str,
        full_profile_sha256: str,
        *,
        prompt_version: str = "",
    ) -> MonitoringMappingDraft:
        project_id = _require_safe_identifier(project_id, "project_id")
        batch_id = _require_safe_identifier(batch_id, "batch_id")
        full_profile_sha256 = _require_sha256(
            full_profile_sha256,
            "full_profile_sha256",
        )
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._validated_source(
                connection,
                project_id=project_id,
                batch_id=batch_id,
                full_profile_sha256=full_profile_sha256,
                prompt_version=prompt_version,
            )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_mapping_drafts
                WHERE project_id = ? AND batch_id = ? AND full_profile_sha256 = ?
                """,
                (project_id, batch_id, full_profile_sha256),
            ).fetchone()
            if existing is not None:
                if existing["source_set_sha256"] != source["source_set_sha256"]:
                    connection.rollback()
                    raise MonitoringMappingStateConflictError(
                        "mapping draft source set changed; create a new batch/profile"
                    )
                field_sources = self._field_sources(
                    connection,
                    project_id,
                    existing["draft_id"],
                )
                connection.commit()
                return self._draft_from_row(
                    existing,
                    field_sources=field_sources,
                )

            draft_id = _mapping_draft_id(
                project_id=project_id,
                batch_id=batch_id,
                full_profile_sha256=full_profile_sha256,
                input_revision_sha256=source["input_revision_sha256"],
                source_set_sha256=source["source_set_sha256"],
            )
            fields = source["fields"]
            expected_job_ids = source["expected_job_ids"]
            preassembly_quality = self._semantic_quality(
                tuple(fields),
                tuple(source["field_sources"]),
            )
            if any(
                item.rule_id == "G-SCALE-002"
                and item.severity.value == "global_blocker"
                for item in preassembly_quality.finding_groups
            ):
                connection.rollback()
                raise MonitoringMappingSourceStateError(
                    "mapping assembly is blocked: scale total or score was "
                    "misclassified as a procedure/record number"
                )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_drafts(
                    draft_id, project_id, batch_id, full_profile_sha256,
                    full_input_sha256, input_revision_json,
                    input_revision_sha256, source_set_sha256, status, version,
                    fields_json, expected_job_ids_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    project_id,
                    batch_id,
                    full_profile_sha256,
                    source["full_input_sha256"],
                    canonical_json(source["input_revision"]),
                    source["input_revision_sha256"],
                    source["source_set_sha256"],
                    MonitoringMappingDraftStatus.DRAFT.value,
                    1,
                    _model_sequence_json(fields),
                    canonical_json(expected_job_ids),
                    _iso(now),
                    _iso(now),
                ),
            )
            for item in source["field_sources"]:
                connection.execute(
                    """
                    INSERT INTO monitoring_mapping_field_sources(
                        draft_id, project_id, domain, source_field, job_id,
                        candidate_id, candidate_content_sha256,
                        input_revision_sha256, prompt_version, evidence_ids_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft_id,
                        project_id,
                        item.domain,
                        item.source_field,
                        item.job_id,
                        item.candidate_id,
                        item.candidate_content_sha256,
                        item.input_revision_sha256,
                        item.prompt_version,
                        canonical_json(item.evidence_ids),
                    ),
                )
            row = connection.execute(
                "SELECT * FROM monitoring_mapping_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            field_sources = self._field_sources(connection, project_id, draft_id)
            connection.commit()
        return self._draft_from_row(row, field_sources=field_sources)

    def get_draft(
        self,
        project_id: str,
        draft_id: str,
    ) -> MonitoringMappingDraft:
        project_id = _require_safe_identifier(project_id, "project_id")
        draft_id = _require_safe_identifier(draft_id, "draft_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_drafts
                WHERE project_id = ? AND draft_id = ?
                """,
                (project_id, draft_id),
            ).fetchone()
            if row is None:
                raise MonitoringMappingNotFoundError("mapping draft not found")
            field_sources = self._field_sources(connection, project_id, draft_id)
        return self._draft_from_row(row, field_sources=field_sources)

    def find_draft_for_batch(
        self,
        project_id: str,
        batch_id: str,
        *,
        full_profile_sha256: str = "",
    ) -> Optional[MonitoringMappingDraft]:
        project_id = _require_safe_identifier(project_id, "project_id")
        batch_id = _require_safe_identifier(batch_id, "batch_id")
        parameters: list[Any] = [project_id, batch_id]
        profile_clause = ""
        if full_profile_sha256:
            profile_clause = " AND full_profile_sha256 = ?"
            parameters.append(
                _require_sha256(
                    full_profile_sha256,
                    "full_profile_sha256",
                )
            )
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM monitoring_mapping_drafts
                WHERE project_id = ? AND batch_id = ?{profile_clause}
                ORDER BY updated_at DESC, draft_id DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                return None
            field_sources = self._field_sources(
                connection,
                project_id,
                row["draft_id"],
            )
        return self._draft_from_row(row, field_sources=field_sources)

    def edit_field(
        self,
        project_id: str,
        draft_id: str,
        *,
        domain: str,
        source_field: str,
        patch: dict[str, Any],
        expected_version: int,
        actor: str,
        idempotency_key: str,
    ) -> MonitoringMappingDraft:
        project_id = _require_safe_identifier(project_id, "project_id")
        draft_id = _require_safe_identifier(draft_id, "draft_id")
        domain = domain.strip()
        source_field = source_field.strip()
        actor = actor.strip()
        idempotency_key = _require_safe_identifier(
            idempotency_key,
            "idempotency_key",
        )
        if not actor:
            raise ValueError("edit actor is required")
        if len(actor) > 160:
            raise ValueError("edit actor exceeds 160 characters")
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        unsupported = set(patch).difference(_EDITABLE_FIELD_KEYS)
        if not patch or unsupported:
            raise ValueError(
                "field edit must contain only editable mapping attributes"
            )
        request_payload = {
            "project_id": project_id,
            "draft_id": draft_id,
            "domain": domain,
            "source_field": source_field,
            "patch": patch,
            "expected_version": expected_version,
            "actor": actor,
        }
        request_sha256 = content_sha256(request_payload)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                """
                SELECT draft_id, request_sha256
                FROM monitoring_mapping_edit_operations
                WHERE project_id = ? AND operation_id = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                if (
                    prior["draft_id"] != draft_id
                    or prior["request_sha256"] != request_sha256
                ):
                    connection.rollback()
                    raise MonitoringMappingStateConflictError(
                        "idempotency key was reused with another edit"
                    )
                row = connection.execute(
                    """
                    SELECT * FROM monitoring_mapping_drafts
                    WHERE project_id = ? AND draft_id = ?
                    """,
                    (project_id, draft_id),
                ).fetchone()
                field_sources = self._field_sources(
                    connection,
                    project_id,
                    draft_id,
                )
                connection.commit()
                return self._draft_from_row(row, field_sources=field_sources)

            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_drafts
                WHERE project_id = ? AND draft_id = ?
                """,
                (project_id, draft_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise MonitoringMappingNotFoundError("mapping draft not found")
            if row["status"] != MonitoringMappingDraftStatus.DRAFT.value:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "confirmed mapping draft cannot be edited"
                )
            if int(row["version"]) != expected_version:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping draft edit lost CAS"
                )
            fields = [
                MonitoringMappingField.model_validate(item)
                for item in json.loads(row["fields_json"])
            ]
            matches = [
                index
                for index, item in enumerate(fields)
                if item.domain == domain and item.source_field == source_field
            ]
            if len(matches) != 1:
                connection.rollback()
                raise MonitoringMappingNotFoundError("mapping field not found")
            index = matches[0]
            payload = fields[index].model_dump(mode="json")
            payload.update(patch)
            payload["domain"] = domain
            payload["source_field"] = source_field
            fields[index] = MonitoringMappingField.model_validate(payload)
            next_version = expected_version + 1
            updated = connection.execute(
                """
                UPDATE monitoring_mapping_drafts
                SET fields_json = ?, version = ?, updated_at = ?
                WHERE project_id = ? AND draft_id = ? AND status = ?
                  AND version = ?
                """,
                (
                    _model_sequence_json(fields),
                    next_version,
                    _iso(now),
                    project_id,
                    draft_id,
                    MonitoringMappingDraftStatus.DRAFT.value,
                    expected_version,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping draft edit lost CAS"
                )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_edit_operations(
                    operation_id, draft_id, project_id, request_sha256,
                    result_version, actor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    draft_id,
                    project_id,
                    request_sha256,
                    next_version,
                    actor,
                    _iso(now),
                ),
            )
            refreshed = connection.execute(
                "SELECT * FROM monitoring_mapping_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            field_sources = self._field_sources(connection, project_id, draft_id)
            connection.commit()
        return self._draft_from_row(refreshed, field_sources=field_sources)

    def confirm(
        self,
        project_id: str,
        draft_id: str,
        *,
        expected_version: int,
        confirmed_by: str,
        confirmation_reason: str,
        idempotency_key: str,
    ) -> MonitoringMappingRevision:
        project_id = _require_safe_identifier(project_id, "project_id")
        draft_id = _require_safe_identifier(draft_id, "draft_id")
        confirmed_by = confirmed_by.strip()
        confirmation_reason = confirmation_reason.strip()
        idempotency_key = _require_safe_identifier(
            idempotency_key,
            "idempotency_key",
        )
        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        if not confirmed_by or not confirmation_reason:
            raise ValueError("confirmation actor and reason are required")
        if len(confirmed_by) > 160:
            raise ValueError("confirmation actor exceeds 160 characters")
        if len(confirmation_reason) > 2_000:
            raise ValueError("confirmation reason exceeds 2000 characters")
        request_payload = {
            "project_id": project_id,
            "draft_id": draft_id,
            "expected_version": expected_version,
            "confirmed_by": confirmed_by,
            "confirmation_reason": confirmation_reason,
        }
        request_sha256 = content_sha256(request_payload)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                """
                SELECT * FROM monitoring_mapping_revisions
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                if prior["confirmation_request_sha256"] != request_sha256:
                    connection.rollback()
                    raise MonitoringMappingStateConflictError(
                        "idempotency key was reused with another confirmation"
                    )
                connection.commit()
                return self._revision_from_row(prior)

            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_drafts
                WHERE project_id = ? AND draft_id = ?
                """,
                (project_id, draft_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise MonitoringMappingNotFoundError("mapping draft not found")
            if row["status"] != MonitoringMappingDraftStatus.DRAFT.value:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping draft is already confirmed"
                )
            if int(row["version"]) != expected_version:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping confirmation lost CAS"
                )
            current_source = self._validated_source(
                connection,
                project_id=project_id,
                batch_id=row["batch_id"],
                full_profile_sha256=row["full_profile_sha256"],
            )
            if (
                current_source["source_set_sha256"] != row["source_set_sha256"]
                or current_source["input_revision_sha256"]
                != row["input_revision_sha256"]
                or current_source["full_input_sha256"] != row["full_input_sha256"]
                or current_source["expected_job_ids"]
                != tuple(json.loads(row["expected_job_ids_json"]))
            ):
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping source changed after draft assembly"
                )
            field_sources = self._field_sources(connection, project_id, draft_id)
            validated_fields = tuple(
                MonitoringMappingField.model_validate(item)
                for item in json.loads(row["fields_json"])
            )
            semantic_quality = self._semantic_quality(
                validated_fields,
                field_sources,
            )
            if semantic_quality.status == SemanticQualityStatus.BLOCKED:
                titles = "；".join(
                    item.title_zh
                    for item in semantic_quality.finding_groups[:4]
                )
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping semantic quality gate is blocked"
                    + (f": {titles}" if titles else "")
                )
            canonical_fields_json = _model_sequence_json(validated_fields)
            revision_seed = {
                "project_id": project_id,
                "draft_id": draft_id,
                "draft_version": expected_version,
                "fields": [
                    item.model_dump(mode="json") for item in validated_fields
                ],
                "field_sources": [
                    item.model_dump(mode="json") for item in field_sources
                ],
                "input_revision_sha256": row["input_revision_sha256"],
                "source_set_sha256": row["source_set_sha256"],
                "semantic_quality_report_sha256": (
                    semantic_quality.report_sha256
                ),
            }
            mapping_revision = "monmaprev_" + content_sha256(revision_seed)[:28]
            connection.execute(
                """
                INSERT INTO monitoring_mapping_revisions(
                    mapping_revision, draft_id, project_id, batch_id,
                    full_profile_sha256, full_input_sha256,
                    input_revision_sha256, source_set_sha256, draft_version,
                    fields_json, field_sources_json,
                    semantic_quality_report_json,
                    semantic_quality_report_sha256,
                    confirmed_by, confirmation_reason, idempotency_key,
                    confirmation_request_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping_revision,
                    draft_id,
                    project_id,
                    row["batch_id"],
                    row["full_profile_sha256"],
                    row["full_input_sha256"],
                    row["input_revision_sha256"],
                    row["source_set_sha256"],
                    expected_version,
                    canonical_fields_json,
                    _model_sequence_json(field_sources),
                    canonical_json(semantic_quality.as_payload()),
                    semantic_quality.report_sha256,
                    confirmed_by,
                    confirmation_reason,
                    idempotency_key,
                    request_sha256,
                    _iso(now),
                ),
            )
            updated = connection.execute(
                """
                UPDATE monitoring_mapping_drafts
                SET status = ?, confirmed_revision_id = ?, updated_at = ?
                WHERE project_id = ? AND draft_id = ? AND status = ?
                  AND version = ?
                """,
                (
                    MonitoringMappingDraftStatus.CONFIRMED.value,
                    mapping_revision,
                    _iso(now),
                    project_id,
                    draft_id,
                    MonitoringMappingDraftStatus.DRAFT.value,
                    expected_version,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise MonitoringMappingStateConflictError(
                    "mapping confirmation lost CAS"
                )
            revision_row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_revisions
                WHERE project_id = ? AND mapping_revision = ?
                """,
                (project_id, mapping_revision),
            ).fetchone()
            connection.commit()
        return self._revision_from_row(revision_row)

    def semantic_quality(
        self,
        project_id: str,
        draft_id: str,
    ) -> MappingSemanticQualityReport:
        draft = self.get_draft(project_id, draft_id)
        return self._semantic_quality(draft.fields, draft.field_sources)

    @staticmethod
    def _semantic_quality(
        fields: tuple[MonitoringMappingField, ...],
        field_sources: tuple[MonitoringMappingFieldSource, ...],
    ) -> MappingSemanticQualityReport:
        return evaluate_mapping_semantic_quality(
            fields=fields,
            expected_fields={
                (item.domain, item.source_field) for item in field_sources
            },
        )

    def get_revision(
        self,
        project_id: str,
        mapping_revision: str,
    ) -> MonitoringMappingRevision:
        project_id = _require_safe_identifier(project_id, "project_id")
        mapping_revision = _require_safe_identifier(
            mapping_revision,
            "mapping_revision",
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_revisions
                WHERE project_id = ? AND mapping_revision = ?
                """,
                (project_id, mapping_revision),
            ).fetchone()
        if row is None:
            raise MonitoringMappingNotFoundError("mapping revision not found")
        return self._revision_from_row(row)

    def _validated_source(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        batch_id: str,
        full_profile_sha256: str,
        prompt_version: str = "",
    ) -> dict[str, Any]:
        source_tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name IN (
                    'monitoring_ai_jobs', 'monitoring_ai_candidates'
                )
                """
            ).fetchall()
        }
        if source_tables != {
            "monitoring_ai_jobs",
            "monitoring_ai_candidates",
        }:
            raise MonitoringMappingSourceStateError(
                "monitoring AI source tables are unavailable"
            )
        rows = connection.execute(
            """
            SELECT * FROM monitoring_ai_jobs
            WHERE project_id = ? AND task_type = ?
            ORDER BY created_at, job_id
            """,
            (project_id, MonitoringAiTaskType.LISTING_FIELD_MAPPING.value),
        ).fetchall()
        matching: list[tuple[sqlite3.Row, dict[str, Any]]] = []
        for row in rows:
            payload = json.loads(row["input_payload_json"])
            profile = payload.get("field_profile")
            if not isinstance(profile, dict):
                continue
            if (
                str(profile.get("batch_id", "")).strip() == batch_id
                and profile.get("full_profile_sha256") == full_profile_sha256
                and (
                    not prompt_version.strip()
                    or str(row["prompt_version"]).strip()
                    == prompt_version.strip()
                )
            ):
                matching.append((row, profile))
        if not matching:
            raise MonitoringMappingSourceStateError(
                "no field-mapping chunks match project, batch and full profile"
            )

        revision_hashes: set[str] = set()
        revisions: dict[str, MonitoringAiInputRevision] = {}
        full_input_hashes: set[str] = set()
        full_field_counts: set[int] = set()
        expected_domain_sets: set[tuple[str, ...]] = set()
        slots: dict[tuple[str, int], tuple[sqlite3.Row, dict[str, Any]]] = {}
        domain_totals: dict[str, int] = {}
        fields: list[MonitoringMappingField] = []
        field_sources: list[MonitoringMappingFieldSource] = []
        field_pairs: set[tuple[str, str]] = set()
        source_jobs: list[dict[str, str]] = []

        for row, profile in matching:
            try:
                status = MonitoringAiJobStatus(row["status"])
            except ValueError as exc:
                raise MonitoringMappingSourceStateError(
                    f"chunk job {row['job_id']} has an unknown status"
                ) from exc
            if status != MonitoringAiJobStatus.COMPLETED:
                raise MonitoringMappingSourceStateError(
                    f"chunk job {row['job_id']} is {status.value}, not completed"
                )
            revision = MonitoringAiInputRevision.model_validate_json(
                row["input_revision_json"]
            )
            if revision.project_id != project_id:
                raise MonitoringMappingSourceStateError(
                    "chunk input revision belongs to another project"
                )
            revision_hash = row["input_revision_sha256"]
            if revision.revision_sha256 != revision_hash:
                raise MonitoringMappingSourceStateError(
                    "chunk input revision hash is inconsistent"
                )
            revision_hashes.add(revision_hash)
            revisions[revision_hash] = revision
            payload = json.loads(row["input_payload_json"])
            if content_sha256(payload) != row["input_payload_sha256"]:
                raise MonitoringMappingSourceStateError(
                    "chunk input payload hash is inconsistent"
                )
            try:
                _require_sha256(row["output_sha256"], "chunk output_sha256")
                full_input_sha256 = _require_sha256(
                    profile.get("full_input_sha256", ""),
                    "full_input_sha256",
                )
            except (TypeError, ValueError) as exc:
                raise MonitoringMappingSourceStateError(
                    "chunk source hash is not canonical"
                ) from exc
            if profile.get("scope") != "complete_profile_chunk":
                raise MonitoringMappingSourceStateError(
                    "field mapping source is not a complete profile chunk"
                )
            if str(profile.get("project_id", "")).strip() != project_id:
                raise MonitoringMappingSourceStateError(
                    "field profile chunk belongs to another project"
                )
            full_input_hashes.add(full_input_sha256)
            try:
                full_field_count = int(profile["full_field_count"])
                chunk_index = int(profile["chunk_index"])
                chunk_total = int(profile["chunk_total"])
                domain_field_count = int(profile["domain_field_count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MonitoringMappingSourceStateError(
                    "chunk count metadata is invalid"
                ) from exc
            if min(full_field_count, chunk_index, chunk_total, domain_field_count) < 1:
                raise MonitoringMappingSourceStateError(
                    "chunk count metadata must be positive"
                )
            if chunk_index > chunk_total:
                raise MonitoringMappingSourceStateError(
                    "chunk index exceeds chunk total"
                )
            full_field_counts.add(full_field_count)
            expected_domains = tuple(
                sorted(
                    {
                        str(item).strip()
                        for item in profile.get("expected_domains", [])
                        if str(item).strip()
                    }
                )
            )
            if not expected_domains:
                raise MonitoringMappingSourceStateError(
                    "chunk does not declare expected domains"
                )
            expected_domain_sets.add(expected_domains)
            domain = str(profile.get("domain", "")).strip()
            if not domain or domain not in expected_domains:
                raise MonitoringMappingSourceStateError(
                    "chunk domain is absent from expected domains"
                )
            slot = (domain, chunk_index)
            if slot in slots:
                raise MonitoringMappingSourceStateError(
                    f"duplicate chunk slot {domain}:{chunk_index}"
                )
            slots[slot] = (row, profile)
            previous_total = domain_totals.setdefault(domain, chunk_total)
            if previous_total != chunk_total:
                raise MonitoringMappingSourceStateError(
                    f"inconsistent chunk total for domain {domain}"
                )
            profile_fields = profile.get("fields")
            if not isinstance(profile_fields, list) or not profile_fields:
                raise MonitoringMappingSourceStateError(
                    "chunk fields are missing"
                )
            if any(
                str(item.get("domain", "")).strip() != domain
                for item in profile_fields
                if isinstance(item, dict)
            ):
                raise MonitoringMappingSourceStateError(
                    "chunk contains a cross-domain profile field"
                )
            expected_business_key = (
                f"listing-field-mapping:{batch_id}:{domain}:"
                f"{chunk_index:04d}-of-{chunk_total:04d}"
            )
            if row["business_key"] != expected_business_key:
                raise MonitoringMappingSourceStateError(
                    "chunk business key does not match its metadata"
                )

            candidate_rows = connection.execute(
                """
                SELECT * FROM monitoring_ai_candidates
                WHERE project_id = ? AND job_id = ?
                ORDER BY created_at, candidate_id
                """,
                (project_id, row["job_id"]),
            ).fetchall()
            if len(candidate_rows) != 1:
                raise MonitoringMappingSourceStateError(
                    f"chunk job {row['job_id']} must have exactly one candidate"
                )
            candidate_row = candidate_rows[0]
            if (
                candidate_row["status"]
                != MonitoringAiCandidateStatus.ACCEPTED.value
            ):
                raise MonitoringMappingSourceStateError(
                    f"chunk candidate {candidate_row['candidate_id']} is not accepted"
                )
            candidate_payload = json.loads(candidate_row["candidate_json"])
            candidate_content_sha256 = content_sha256(candidate_payload)
            candidate_payload["status"] = candidate_row["status"]
            candidate = MonitoringAiCandidate.model_validate(candidate_payload)
            if (
                candidate.candidate_id != candidate_row["candidate_id"]
                or candidate.project_id != project_id
                or candidate.job_id != row["job_id"]
                or candidate.task_type
                != MonitoringAiTaskType.LISTING_FIELD_MAPPING
                or candidate.candidate_type != "listing_field_mapping_set"
                or candidate.input_revision_sha256 != revision_hash
                or candidate.prompt_version != row["prompt_version"]
                or candidate_row["task_type"]
                != MonitoringAiTaskType.LISTING_FIELD_MAPPING.value
                or candidate_row["input_revision_sha256"] != revision_hash
            ):
                raise MonitoringMappingSourceStateError(
                    "candidate does not match its field-mapping job"
                )
            raw_mappings = candidate.structured_payload.get("field_mappings")
            if not isinstance(raw_mappings, list) or not raw_mappings:
                raise MonitoringMappingSourceStateError(
                    "candidate field mappings are missing"
                )
            chunk_profile_pairs = {
                (
                    str(item.get("domain", "")).strip(),
                    str(item.get("field", "")).strip(),
                )
                for item in profile_fields
                if isinstance(item, dict)
            }
            if len(chunk_profile_pairs) != len(profile_fields):
                raise MonitoringMappingSourceStateError(
                    "chunk profile fields are duplicate or malformed"
                )
            candidate_fields: list[MonitoringMappingField] = []
            known_evidence = {
                item.evidence_id: item for item in candidate.evidence
            }
            for raw_mapping in raw_mappings:
                mapping_payload = dict(raw_mapping)
                date_constraints = _date_constraints_from_profile_evidence(
                    mapping_payload,
                    known_evidence,
                )
                if date_constraints is not None:
                    mapping_payload["value_constraints"] = date_constraints
                try:
                    mapped = MonitoringMappingField.model_validate(
                        mapping_payload
                    )
                except Exception as exc:
                    raise MonitoringMappingSourceStateError(
                        "candidate mapping payload is invalid"
                    ) from exc
                mapped = _normalize_known_export_context(mapped)
                mapped = _normalize_known_coding_support_metadata(mapped)
                mapped = _quarantine_multi_action_ip_role(mapped)
                mapped = _quarantine_low_confidence_unresolved_role(mapped)
                pair = (mapped.domain, mapped.source_field)
                if pair in field_pairs:
                    raise MonitoringMappingSourceStateError(
                        f"field appears in multiple chunks: {pair[0]}.{pair[1]}"
                    )
                field_pairs.add(pair)
                candidate_fields.append(mapped)
                if not set(mapped.evidence_ids).issubset(known_evidence):
                    raise MonitoringMappingSourceStateError(
                        "mapping references unknown candidate evidence"
                    )
                field_sources.append(
                    MonitoringMappingFieldSource(
                        domain=mapped.domain,
                        source_field=mapped.source_field,
                        job_id=row["job_id"],
                        candidate_id=candidate.candidate_id,
                        candidate_content_sha256=candidate_content_sha256,
                        input_revision_sha256=revision_hash,
                        prompt_version=candidate.prompt_version,
                        evidence_ids=mapped.evidence_ids,
                    )
                )
            candidate_pairs = {
                (item.domain, item.source_field) for item in candidate_fields
            }
            if candidate_pairs != chunk_profile_pairs or len(candidate_fields) != len(
                profile_fields
            ):
                raise MonitoringMappingSourceStateError(
                    "candidate does not cover its complete profile chunk exactly once"
                )
            if len(profile_fields) > domain_field_count:
                raise MonitoringMappingSourceStateError(
                    "chunk exceeds declared domain field count"
                )
            fields.extend(candidate_fields)
            source_jobs.append(
                {
                    "job_id": row["job_id"],
                    "candidate_id": candidate.candidate_id,
                    "candidate_content_sha256": candidate_content_sha256,
                    "input_payload_sha256": row["input_payload_sha256"],
                    "output_sha256": row["output_sha256"],
                }
            )

        if len(revision_hashes) != 1:
            raise MonitoringMappingSourceStateError(
                "field mapping chunks do not share one input revision"
            )
        if len(full_input_hashes) != 1 or len(full_field_counts) != 1:
            raise MonitoringMappingSourceStateError(
                "field mapping chunks disagree on full profile metadata"
            )
        if len(expected_domain_sets) != 1:
            raise MonitoringMappingSourceStateError(
                "field mapping chunks disagree on expected domains"
            )
        expected_domains = next(iter(expected_domain_sets))
        if set(domain_totals) != set(expected_domains):
            missing = sorted(set(expected_domains).difference(domain_totals))
            raise MonitoringMappingSourceStateError(
                "expected field mapping domains are missing: " + ", ".join(missing)
            )
        for domain, total in domain_totals.items():
            present = {index for seen_domain, index in slots if seen_domain == domain}
            expected = set(range(1, total + 1))
            if present != expected:
                raise MonitoringMappingSourceStateError(
                    f"domain {domain} has missing or extra chunk slots"
                )
            domain_count_values = {
                int(profile["domain_field_count"])
                for (seen_domain, _), (_, profile) in slots.items()
                if seen_domain == domain
            }
            if len(domain_count_values) != 1:
                raise MonitoringMappingSourceStateError(
                    f"domain {domain} has inconsistent field counts"
                )
            actual_domain_count = sum(
                len(profile["fields"])
                for (seen_domain, _), (_, profile) in slots.items()
                if seen_domain == domain
            )
            if actual_domain_count != next(iter(domain_count_values)):
                raise MonitoringMappingSourceStateError(
                    f"domain {domain} field coverage is incomplete"
                )
        full_field_count = next(iter(full_field_counts))
        if len(fields) != full_field_count or len(field_pairs) != full_field_count:
            raise MonitoringMappingSourceStateError(
                "assembled fields do not match the declared full field count"
            )
        expected_job_ids = tuple(
            sorted(row["job_id"] for row, _ in matching)
        )
        source_set_sha256 = content_sha256(
            sorted(source_jobs, key=lambda item: item["job_id"])
        )
        revision_hash = next(iter(revision_hashes))
        fields = _anchor_complete_meddra_source_chains(
            fields,
            field_sources,
            input_revision_sha256=revision_hash,
            source_set_sha256=source_set_sha256,
            expected_job_ids=expected_job_ids,
        )
        fields = _downgrade_unverifiable_standardized_coding(fields)
        fields = sorted(fields, key=lambda item: (item.domain, item.source_field))
        field_sources = sorted(
            field_sources,
            key=lambda item: (item.domain, item.source_field),
        )
        return {
            "input_revision": revisions[revision_hash],
            "input_revision_sha256": revision_hash,
            "full_input_sha256": next(iter(full_input_hashes)),
            "source_set_sha256": source_set_sha256,
            "fields": tuple(fields),
            "field_sources": tuple(field_sources),
            "expected_job_ids": expected_job_ids,
        }

    def _field_sources(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        draft_id: str,
    ) -> tuple[MonitoringMappingFieldSource, ...]:
        rows = connection.execute(
            """
            SELECT * FROM monitoring_mapping_field_sources
            WHERE project_id = ? AND draft_id = ?
            ORDER BY domain, source_field
            """,
            (project_id, draft_id),
        ).fetchall()
        try:
            return tuple(
                self._field_source_from_row(
                    row,
                    expected_project_id=project_id,
                    expected_draft_id=draft_id,
                )
                for row in rows
            )
        except Exception as exc:
            raise MonitoringMappingStateConflictError(
                "persisted mapping source lineage is invalid"
            ) from exc

    @staticmethod
    def _field_source_from_row(
        row: sqlite3.Row,
        *,
        expected_project_id: str,
        expected_draft_id: str,
    ) -> MonitoringMappingFieldSource:
        if row["project_id"] != expected_project_id:
            raise ValueError("mapping source project binding is invalid")
        if row["draft_id"] != expected_draft_id:
            raise ValueError("mapping source draft binding is invalid")
        return MonitoringMappingDraftRepository._field_source_from_payload(
            {
                "domain": row["domain"],
                "source_field": row["source_field"],
                "job_id": row["job_id"],
                "candidate_id": row["candidate_id"],
                "candidate_content_sha256": row["candidate_content_sha256"],
                "input_revision_sha256": row["input_revision_sha256"],
                "prompt_version": row["prompt_version"],
                "evidence_ids": json.loads(row["evidence_ids_json"]),
            }
        )

    @staticmethod
    def _field_source_from_payload(
        payload: Mapping[str, object],
    ) -> MonitoringMappingFieldSource:
        expected_keys = {
            "domain",
            "source_field",
            "job_id",
            "candidate_id",
            "candidate_content_sha256",
            "input_revision_sha256",
            "prompt_version",
            "evidence_ids",
        }
        if set(payload) != expected_keys:
            raise ValueError("mapping source payload shape is invalid")

        def required_text(value: object, label: str) -> str:
            if not isinstance(value, str) or not value:
                raise ValueError(f"mapping source {label} is invalid")
            cleaned = value.strip()
            if not cleaned or cleaned != value:
                raise ValueError(f"mapping source {label} is invalid")
            return cleaned

        def lowercase_sha256(value: object, label: str) -> str:
            cleaned = required_text(value, label)
            if cleaned != cleaned.lower() or _require_sha256(cleaned, label) != cleaned:
                raise ValueError(f"mapping source {label} is invalid")
            return cleaned

        evidence_payload = payload.get("evidence_ids")
        if (
            not isinstance(evidence_payload, list)
            or not evidence_payload
            or any(
                not isinstance(item, str) or not item.strip()
                for item in evidence_payload
            )
        ):
            raise ValueError("mapping source evidence IDs are invalid")
        evidence_ids = tuple(item.strip() for item in evidence_payload)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("mapping source evidence IDs are invalid")
        return MonitoringMappingFieldSource(
            domain=required_text(payload.get("domain"), "domain"),
            source_field=required_text(
                payload.get("source_field"),
                "source_field",
            ),
            job_id=required_text(payload.get("job_id"), "job_id"),
            candidate_id=required_text(
                payload.get("candidate_id"),
                "candidate_id",
            ),
            candidate_content_sha256=lowercase_sha256(
                payload.get("candidate_content_sha256"),
                "candidate_content_sha256",
            ),
            input_revision_sha256=lowercase_sha256(
                payload.get("input_revision_sha256"),
                "input_revision_sha256",
            ),
            prompt_version=required_text(
                payload.get("prompt_version"),
                "prompt_version",
            ),
            evidence_ids=evidence_ids,
        )

    def _draft_from_row(
        self,
        row: sqlite3.Row,
        *,
        field_sources: tuple[MonitoringMappingFieldSource, ...] | None = None,
    ) -> MonitoringMappingDraft:
        if field_sources is None:
            with self._connect() as source_connection:
                field_sources = self._field_sources(
                    source_connection,
                    row["project_id"],
                    row["draft_id"],
                )
        try:
            input_revision = MonitoringAiInputRevision.model_validate_json(
                row["input_revision_json"]
            )
            input_revision_sha256 = _require_sha256(
                row["input_revision_sha256"],
                "input_revision_sha256",
            )
            full_profile_sha256 = _require_sha256(
                row["full_profile_sha256"],
                "full_profile_sha256",
            )
            full_input_sha256 = _require_sha256(
                row["full_input_sha256"],
                "full_input_sha256",
            )
            source_set_sha256 = _require_sha256(
                row["source_set_sha256"],
                "source_set_sha256",
            )
            fields = tuple(
                MonitoringMappingField.model_validate(item)
                for item in json.loads(row["fields_json"])
            )
            expected_job_ids = tuple(
                str(item).strip()
                for item in json.loads(row["expected_job_ids_json"])
            )
            draft = MonitoringMappingDraft(
                draft_id=row["draft_id"],
                project_id=row["project_id"],
                batch_id=row["batch_id"],
                full_profile_sha256=full_profile_sha256,
                full_input_sha256=full_input_sha256,
                input_revision=input_revision,
                input_revision_sha256=input_revision_sha256,
                source_set_sha256=source_set_sha256,
                status=row["status"],
                version=int(row["version"]),
                fields=fields,
                field_sources=field_sources,
                expected_job_ids=expected_job_ids,
                confirmed_revision_id=row["confirmed_revision_id"],
                created_at=_datetime(row["created_at"]),
                updated_at=_datetime(row["updated_at"]),
            )
        except Exception as exc:
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft is invalid"
            ) from exc

        if input_revision.revision_sha256 != input_revision_sha256:
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft input revision hash mismatch"
            )
        if draft.draft_id != _mapping_draft_id(
            project_id=draft.project_id,
            batch_id=draft.batch_id,
            full_profile_sha256=draft.full_profile_sha256,
            input_revision_sha256=draft.input_revision_sha256,
            source_set_sha256=draft.source_set_sha256,
        ):
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft anchor identity mismatch"
            )
        if len(draft.expected_job_ids) != len(set(draft.expected_job_ids)) or any(
            not item for item in draft.expected_job_ids
        ):
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft expected job IDs are invalid"
            )
        field_pairs = [(item.domain, item.source_field) for item in draft.fields]
        source_pairs = [
            (item.domain, item.source_field) for item in draft.field_sources
        ]
        if len(field_pairs) != len(set(field_pairs)) or set(field_pairs) != set(
            source_pairs
        ):
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft source lineage does not match fields"
            )
        if any(
            item.input_revision_sha256 != draft.input_revision_sha256
            for item in draft.field_sources
        ):
            raise MonitoringMappingStateConflictError(
                "persisted mapping draft source lineage revision mismatch"
            )
        return draft

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> MonitoringMappingRevision:
        try:
            def required_text(value: object, label: str) -> str:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"mapping revision {label} is invalid")
                cleaned = value.strip()
                if not cleaned or cleaned != value:
                    raise ValueError(f"mapping revision {label} is invalid")
                return cleaned

            def lowercase_sha256(value: object, label: str) -> str:
                cleaned = required_text(value, label)
                if cleaned != cleaned.lower() or _require_sha256(cleaned, label) != cleaned:
                    raise ValueError(f"mapping revision {label} is invalid")
                return cleaned

            mapping_revision = required_text(
                row["mapping_revision"],
                "mapping_revision",
            )
            if not mapping_revision.startswith("monmaprev_"):
                raise ValueError("mapping revision identity is invalid")
            draft_id = _require_safe_identifier(
                required_text(row["draft_id"], "draft_id"),
                "draft_id",
            )
            project_id = _require_safe_identifier(
                required_text(row["project_id"], "project_id"),
                "project_id",
            )
            batch_id = _require_safe_identifier(
                required_text(row["batch_id"], "batch_id"),
                "batch_id",
            )
            full_profile_sha256 = lowercase_sha256(
                row["full_profile_sha256"],
                "full_profile_sha256",
            )
            full_input_sha256 = lowercase_sha256(
                row["full_input_sha256"],
                "full_input_sha256",
            )
            input_revision_sha256 = lowercase_sha256(
                row["input_revision_sha256"],
                "input_revision_sha256",
            )
            source_set_sha256 = lowercase_sha256(
                row["source_set_sha256"],
                "source_set_sha256",
            )
            draft_version = int(row["draft_version"])
            if draft_version < 1:
                raise ValueError("mapping revision draft version is invalid")

            raw_fields = json.loads(row["fields_json"])
            raw_sources = json.loads(row["field_sources_json"])
            if not isinstance(raw_fields, list) or not raw_fields:
                raise ValueError("mapping revision fields are invalid")
            if not isinstance(raw_sources, list) or not raw_sources:
                raise ValueError("mapping revision field sources are invalid")
            fields = tuple(
                MonitoringMappingField.model_validate(item)
                for item in raw_fields
            )
            field_sources = tuple(
                MonitoringMappingDraftRepository._field_source_from_payload(item)
                for item in raw_sources
                if isinstance(item, Mapping)
            )
            if len(field_sources) != len(raw_sources):
                raise ValueError("mapping revision field sources are invalid")
            field_pairs = [(item.domain, item.source_field) for item in fields]
            source_pairs = [
                (item.domain, item.source_field) for item in field_sources
            ]
            if (
                len(field_pairs) != len(set(field_pairs))
                or len(source_pairs) != len(set(source_pairs))
                or field_pairs != source_pairs
            ):
                raise MonitoringMappingStateConflictError(
                    "persisted mapping revision source lineage does not match fields"
                )
            if any(
                item.input_revision_sha256 != input_revision_sha256
                for item in field_sources
            ):
                raise MonitoringMappingStateConflictError(
                    "persisted mapping revision source lineage revision mismatch"
                )

            semantic_quality_report = json.loads(
                row["semantic_quality_report_json"]
                if "semantic_quality_report_json" in row.keys()
                else "{}"
            )
            semantic_quality_report_sha256 = (
                row["semantic_quality_report_sha256"]
                if "semantic_quality_report_sha256" in row.keys()
                else ""
            )
            if not isinstance(semantic_quality_report, dict):
                raise ValueError("mapping semantic quality report is invalid")
            if semantic_quality_report_sha256:
                semantic_quality_report_sha256 = lowercase_sha256(
                    semantic_quality_report_sha256,
                    "semantic_quality_report_sha256",
                )
                if semantic_quality_report.get("report_sha256") != (
                    semantic_quality_report_sha256
                ):
                    raise MonitoringMappingStateConflictError(
                        "persisted mapping semantic quality report identity mismatch"
                    )
                report_without_hash = {
                    key: value
                    for key, value in semantic_quality_report.items()
                    if key != "report_sha256"
                }
                if content_sha256(report_without_hash) != semantic_quality_report_sha256:
                    raise MonitoringMappingStateConflictError(
                        "persisted mapping semantic quality report hash mismatch"
                    )
                revision_seed = {
                    "project_id": project_id,
                    "draft_id": draft_id,
                    "draft_version": draft_version,
                    "fields": [item.model_dump(mode="json") for item in fields],
                    "field_sources": [
                        item.model_dump(mode="json") for item in field_sources
                    ],
                    "input_revision_sha256": input_revision_sha256,
                    "source_set_sha256": source_set_sha256,
                    "semantic_quality_report_sha256": (
                        semantic_quality_report_sha256
                    ),
                }
                expected_mapping_revision = (
                    "monmaprev_" + content_sha256(revision_seed)[:28]
                )
                if mapping_revision != expected_mapping_revision:
                    raise MonitoringMappingStateConflictError(
                        "persisted mapping revision identity mismatch"
                    )
            elif semantic_quality_report != {}:
                raise ValueError(
                    "mapping semantic quality report hash is missing"
                )

            return MonitoringMappingRevision(
                mapping_revision=mapping_revision,
                draft_id=draft_id,
                project_id=project_id,
                batch_id=batch_id,
                full_profile_sha256=full_profile_sha256,
                full_input_sha256=full_input_sha256,
                input_revision_sha256=input_revision_sha256,
                source_set_sha256=source_set_sha256,
                draft_version=draft_version,
                fields=fields,
                field_sources=field_sources,
                semantic_quality_report=semantic_quality_report,
                semantic_quality_report_sha256=semantic_quality_report_sha256,
                confirmed_by=required_text(row["confirmed_by"], "confirmed_by"),
                confirmation_reason=required_text(
                    row["confirmation_reason"],
                    "confirmation_reason",
                ),
                created_at=_datetime(required_text(row["created_at"], "created_at")),
            )
        except MonitoringMappingStateConflictError:
            raise
        except Exception as exc:
            raise MonitoringMappingStateConflictError(
                "persisted mapping revision is invalid"
            ) from exc


def _date_constraints_from_profile_evidence(
    mapping: dict[str, Any],
    evidence_by_id: dict[str, Any],
) -> Optional[dict[str, Any]]:
    role = str(mapping.get("recommended_role") or "").strip().casefold()
    source_field = str(mapping.get("source_field") or "").strip().upper()
    date_like_role = any(
        marker in role
        for marker in ("date", "datetime", "日期", "时间")
    )
    date_like_field = bool(
        re.search(r"(?:DAT|DATE|DTC|DT)$", source_field)
    )
    if not date_like_role and not date_like_field:
        return None

    observed_precisions: set[str] = set()
    for evidence_id in mapping.get("evidence_ids") or ():
        evidence = evidence_by_id.get(str(evidence_id))
        raw_fields = getattr(evidence, "raw_fields", {}) if evidence else {}
        for value in _profile_observed_values(raw_fields):
            compact = value.strip()
            if not compact or not _PARTIAL_DATE_VALUE_RE.fullmatch(compact):
                continue
            components = re.split(r"[-/.]", compact)
            unknown = {
                "UK",
                "UNK",
                "UNKNOWN",
                "XX",
                "00",
            }
            if len(components) == 1 or (
                len(components) >= 2
                and str(components[1]).upper() in unknown
            ):
                observed_precisions.add("year")
            elif len(components) == 2 or (
                len(components) >= 3
                and str(components[2]).upper() in unknown
            ):
                observed_precisions.add("month")
            else:
                observed_precisions.add("partial")
    if not observed_precisions:
        return None
    return {
        "date_precision": (
            next(iter(observed_precisions))
            if len(observed_precisions) == 1
            else "mixed"
        ),
        "supports_exact_date": False,
        "observed_precisions": sorted(observed_precisions),
        "basis": "frozen_field_profile_observation",
    }


def _profile_observed_values(raw_fields: Any) -> tuple[str, ...]:
    if not isinstance(raw_fields, dict):
        return ()
    values: list[str] = []
    for key in ("representative_values", "top_values", "anomaly_examples"):
        for item in raw_fields.get(key) or ():
            if isinstance(item, dict):
                raw_value = item.get("value")
            else:
                raw_value = item
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if value:
                values.append(value)
    return tuple(dict.fromkeys(values))
