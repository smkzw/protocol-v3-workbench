from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional, Sequence


PROTOCOL_VERSION_STATUSES = ("draft", "confirmed", "superseded")
PROTOCOL_APPLICABILITY_STATUSES = (
    "version_date_only",
    "project_effective_confirmed",
    "site_specific",
)
PROTOCOL_APPLICABILITY_ASSIGNMENT_STATUSES = (
    "candidate",
    "confirmed",
    "retired",
)
PROTOCOL_FACT_STATUSES = (
    "ai_candidate",
    "medically_confirmed",
    "superseded",
    "missing_source",
)
RULE_PACK_STATUSES = ("draft", "shadow", "confirmed", "published", "retired")
RULE_STATUSES = ("candidate", "confirmed", "enabled", "disabled", "superseded")
RULE_SEVERITIES = ("low", "medium", "high", "critical")
RULE_CONFIDENCE_LEVELS = ("low", "medium", "high", "deterministic")
RULE_EXECUTORS = (
    "field_predicate",
    "cross_record",
    "temporal",
    "manual_review",
)
RE_REVIEW_STATUSES = ("open", "in_review", "resolved", "cancelled")
RETROSPECTIVE_POLICIES = (
    "prospective_only",
    "open_risks_only",
    "all_eligible_batches",
    "manual_scope",
)
SHADOW_RUN_STATUSES = ("completed", "failed")
GOLD_CASE_COVERAGE_LABELS = ("positive", "negative", "boundary")
DIAGNOSTIC_CASE_CATEGORIES = (
    "missing_input",
    "conflicting_input",
    "invalid_input",
    "incomplete_evidence",
    "unresolved_applicability",
    "unresolved_mapping",
)

PROTOCOL_FACT_TYPES = (
    "visit_schedule",
    "visit_window",
    "eligibility_inclusion",
    "eligibility_exclusion",
    "study_treatment_regimen",
    "study_treatment_change",
    "study_treatment_adherence",
    "concomitant_medication_allowed",
    "concomitant_medication_restricted",
    "concomitant_medication_prohibited",
    "concomitant_medication_rescue",
    "concomitant_medication_washout",
    "efficacy_assessment",
    "safety_assessment",
    "aesi_definition",
    "early_withdrawal",
    "protocol_deviation",
    "data_quality",
)

CLINICAL_DOMAINS = (
    "visit",
    "eligibility",
    "study_treatment",
    "concomitant_medication",
    "efficacy",
    "safety",
    "protocol_deviation",
    "data_quality",
)

FACT_TYPE_CLINICAL_DOMAIN = {
    "visit_schedule": "visit",
    "visit_window": "visit",
    "eligibility_inclusion": "eligibility",
    "eligibility_exclusion": "eligibility",
    "study_treatment_regimen": "study_treatment",
    "study_treatment_change": "study_treatment",
    "study_treatment_adherence": "study_treatment",
    "concomitant_medication_allowed": "concomitant_medication",
    "concomitant_medication_restricted": "concomitant_medication",
    "concomitant_medication_prohibited": "concomitant_medication",
    "concomitant_medication_rescue": "concomitant_medication",
    "concomitant_medication_washout": "concomitant_medication",
    "efficacy_assessment": "efficacy",
    "safety_assessment": "safety",
    "aesi_definition": "safety",
    "early_withdrawal": "visit",
    "protocol_deviation": "protocol_deviation",
    "data_quality": "data_quality",
}

RULE_FAMILIES = (
    "ae_mh_missing_review",
    "cs_ncs_review",
    "study_treatment_change",
    "study_treatment_adherence",
    "concomitant_medication_policy",
    "visit_window_and_order",
    "eligibility_continuity",
    "ae_sae_aesi_consistency",
    "efficacy_endpoint_completeness",
    "cross_domain_consistency",
    "data_quality",
)
P7C_EXTENDED_RULE_FAMILIES = (
    "laboratory_abnormality",
    "ctcae_longitudinal_worsening",
)
ALL_RULE_FAMILIES = RULE_FAMILIES + P7C_EXTENDED_RULE_FAMILIES
INITIAL_RELEASE_RULE_FAMILIES = (
    "ae_mh_missing_review",
    "cs_ncs_review",
    "concomitant_medication_policy",
    "study_treatment_change",
    "study_treatment_adherence",
    "visit_window_and_order",
    "laboratory_abnormality",
    "ctcae_longitudinal_worsening",
)

RULE_FAMILY_CLINICAL_DOMAINS = {
    "ae_mh_missing_review": frozenset({"safety"}),
    "cs_ncs_review": frozenset({"safety"}),
    "study_treatment_change": frozenset({"study_treatment"}),
    "study_treatment_adherence": frozenset({"study_treatment"}),
    "concomitant_medication_policy": frozenset({"concomitant_medication"}),
    "visit_window_and_order": frozenset({"visit"}),
    "eligibility_continuity": frozenset({"eligibility"}),
    "ae_sae_aesi_consistency": frozenset({"safety"}),
    "laboratory_abnormality": frozenset({"safety"}),
    "ctcae_longitudinal_worsening": frozenset({"safety"}),
    "efficacy_endpoint_completeness": frozenset({"efficacy"}),
    "cross_domain_consistency": frozenset(CLINICAL_DOMAINS),
    "data_quality": frozenset({"data_quality", "protocol_deviation"}),
}

RULE_FAMILY_ALLOWED_DATA_DOMAINS = {
    "ae_mh_missing_review": frozenset({"AE", "MH", "CM", "LB", "DS", "EC"}),
    "cs_ncs_review": frozenset({"LB", "VS", "EG", "AE", "MH"}),
    "study_treatment_change": frozenset({"EX", "EC", "DA", "IP", "CM", "DS", "SV"}),
    "study_treatment_adherence": frozenset({"EX", "EC", "DA", "IP", "DS", "SV"}),
    "concomitant_medication_policy": frozenset({"CM", "AE", "MH", "LB", "EX", "SV"}),
    "visit_window_and_order": frozenset({"SV", "DS", "DV", "EX", "LB", "QS"}),
    "eligibility_continuity": frozenset(
        {"IE", "DM", "MH", "CM", "LB", "VS", "QS", "AE", "SV", "EX"}
    ),
    "ae_sae_aesi_consistency": frozenset({"AE", "SAE", "AESI", "CM", "MH", "LB", "DS"}),
    "laboratory_abnormality": frozenset({"LB", "VS", "EG", "AE", "MH"}),
    "ctcae_longitudinal_worsening": frozenset({"LB", "AE", "VS", "EG"}),
    "efficacy_endpoint_completeness": frozenset({"QS", "FA", "RS", "LB", "SV", "DS"}),
    "cross_domain_consistency": frozenset(
        {"AE", "SAE", "AESI", "MH", "CM", "LB", "VS", "EX", "EC", "DA", "IP", "SV", "DS", "DV", "IE", "QS", "FA", "RS"}
    ),
    "data_quality": frozenset(
        {"AE", "SAE", "AESI", "MH", "CM", "LB", "VS", "EX", "EC", "DA", "IP", "SV", "DS", "DV", "IE", "QS", "FA", "RS"}
    ),
}

RULE_FAMILY_REQUIRED_DATA_DOMAIN_GROUPS = {
    "study_treatment_change": (frozenset({"EX", "EC", "DA", "IP"}),),
    "study_treatment_adherence": (frozenset({"EX", "EC", "DA", "IP"}),),
    "concomitant_medication_policy": (frozenset({"CM"}),),
    "visit_window_and_order": (frozenset({"SV"}),),
    "ae_mh_missing_review": (frozenset({"AE", "MH"}),),
    "cs_ncs_review": (frozenset({"LB", "VS", "EG"}),),
    "ae_sae_aesi_consistency": (frozenset({"AE", "SAE", "AESI"}),),
    "laboratory_abnormality": (frozenset({"LB", "VS", "EG"}),),
    "ctcae_longitudinal_worsening": (frozenset({"LB"}),),
}
_STUDY_TREATMENT_DATA_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_CONCOMITANT_MEDICATION_DATA_DOMAIN = "CM"
_LINEAGE_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_LINEAGE_ALLOWED_SOURCE_TYPES = frozenset(
    {"raw_listing_field", "auditable_base_value"}
)
_LINEAGE_PROHIBITED_SOURCE_TYPES = frozenset(
    {
        "medical_conclusion",
        "model_output",
        "precomputed_medical_conclusion",
        "review_status",
    }
)
_LINEAGE_CONCLUSION_MARKERS = (
    "medical_conclusion",
    "model_output",
    "precomputed_medical_conclusion",
    "review_status",
)
_LINEAGE_CALCULATION_RE = re.compile(r"^[A-Za-z0-9_+\-*/().,\s]+$")
_LINEAGE_CALCULATION_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LINEAGE_DETERMINISTIC_FUNCTIONS = frozenset(
    {
        "abs",
        "count_non_missing",
        "date_diff_days",
        "maximum",
        "minimum",
        "round",
        "scheduled_dose_count",
    }
)
_PREDICATE_FIELD_KEYS = frozenset(
    {
        "field",
        "other_field",
        "numerator_field",
        "denominator_field",
        "related_field",
        "current_field",
        "related_date_field",
        "current_date_field",
    }
)

_ALLOWED_PREDICATE_OPERATORS = {
    "all",
    "any",
    "not",
    "exists",
    "missing",
    "eq",
    "ne",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "regex",
    "changed",
    "date_delta_days",
    "date_compare",
    "date_delta_range",
    "ratio_range",
    "no_corresponding_record",
}
_KEY_RE = re.compile(r"^[a-z][a-z0-9_.:-]{2,159}$")


class MonitoringProtocolRuleError(ValueError):
    pass


def _required_text(value: Any, field_name: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise MonitoringProtocolRuleError(f"{field_name} is required")
    return normalized


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    normalized = _required_text(value, field_name)
    if len(normalized) > limit:
        raise MonitoringProtocolRuleError(f"{field_name} exceeds {limit} characters")
    return normalized


def _optional_text(value: Any, limit: int = 500) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) > limit:
        raise MonitoringProtocolRuleError(f"text exceeds {limit} characters")
    return normalized


def _exact_identifier(value: Any, field_name: str, limit: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringProtocolRuleError(f"{field_name} is required")
    if len(normalized) > limit:
        raise MonitoringProtocolRuleError(f"{field_name} exceeds {limit} characters")
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return f"{prefix}_{digest.hexdigest()[:24]}"


def _normalize_key(value: str, field_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    if not _KEY_RE.fullmatch(normalized):
        raise MonitoringProtocolRuleError(
            f"{field_name} must use lowercase project-neutral tokens"
        )
    return normalized


def _normalize_date(value: str, field_name: str, *, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        if required:
            raise MonitoringProtocolRuleError(f"{field_name} is required")
        return ""
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as exc:
        raise MonitoringProtocolRuleError(
            f"{field_name} must be an ISO date"
        ) from exc


def _validate_enum(value: str, field_name: str, allowed: Sequence[str]) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise MonitoringProtocolRuleError(
            f"{field_name} must be one of {', '.join(allowed)}"
        )
    return normalized


def _validate_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MonitoringProtocolRuleError(f"{field_name} must be an object")
    serialized = _canonical_json(value)
    if len(serialized) > 100_000:
        raise MonitoringProtocolRuleError(f"{field_name} is too large")
    return json.loads(serialized)


def validate_predicate_expression(expression: Mapping[str, Any]) -> dict[str, Any]:
    canonical = _validate_mapping(expression, "trigger_expression")
    _validate_predicate_node(canonical, path="trigger_expression")
    return canonical


def _validate_predicate_node(node: Any, *, path: str) -> None:
    if not isinstance(node, dict) or len(node) != 1:
        raise MonitoringProtocolRuleError(
            f"{path} must contain exactly one predicate operator"
        )
    operator, operand = next(iter(node.items()))
    if operator not in _ALLOWED_PREDICATE_OPERATORS:
        raise MonitoringProtocolRuleError(f"{path} uses unsupported operator: {operator}")
    if operator in {"all", "any"}:
        if not isinstance(operand, list) or not operand:
            raise MonitoringProtocolRuleError(f"{path}.{operator} must be a non-empty list")
        for index, child in enumerate(operand):
            _validate_predicate_node(child, path=f"{path}.{operator}[{index}]")
        return
    if operator == "not":
        _validate_predicate_node(operand, path=f"{path}.not")
        return
    if not isinstance(operand, dict):
        raise MonitoringProtocolRuleError(f"{path}.{operator} must be an object")
    if operator in {"exists", "missing", "changed"}:
        if set(operand) != {"field"}:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain only field"
            )
    elif operator == "date_compare":
        if set(operand) != {"field", "other_field", "relation"}:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain field, other_field and relation"
            )
        _validate_distinct_fields(operand, path=f"{path}.{operator}")
        if operand.get("relation") not in {
            "before",
            "before_or_equal",
            "same",
            "after_or_equal",
            "after",
        }:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.relation is not supported"
            )
    elif operator == "date_delta_days":
        if set(operand) != {"field", "other_field", "value"}:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain field, other_field and value"
            )
        _validate_distinct_fields(operand, path=f"{path}.{operator}")
        value = operand.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.value must be a non-negative number"
            )
    elif operator == "date_delta_range":
        allowed = {"field", "other_field", "min_days", "max_days"}
        if not set(operand).issubset(allowed) or not {
            "field",
            "other_field",
        }.issubset(operand):
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain field, other_field and at least "
                "one of min_days or max_days"
            )
        _validate_distinct_fields(operand, path=f"{path}.{operator}")
        _validate_numeric_range(
            operand,
            minimum_key="min_days",
            maximum_key="max_days",
            path=f"{path}.{operator}",
        )
    elif operator == "ratio_range":
        allowed = {
            "numerator_field",
            "denominator_field",
            "multiplier",
            "min_value",
            "max_value",
        }
        if set(operand) != allowed:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain numerator_field, "
                "denominator_field, multiplier, min_value and max_value"
            )
        numerator = str(operand.get("numerator_field", "")).strip()
        denominator = str(operand.get("denominator_field", "")).strip()
        if not numerator or not denominator or numerator == denominator:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} requires two different fields"
            )
        multiplier = operand.get("multiplier")
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or multiplier <= 0
        ):
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.multiplier must be a positive number"
            )
        _validate_numeric_range(
            operand,
            minimum_key="min_value",
            maximum_key="max_value",
            path=f"{path}.{operator}",
            require_both=True,
        )
    elif operator == "no_corresponding_record":
        legacy_shapes = ({"domain"}, {"domain", "field", "value"})
        structured_keys = {"domain", "match", "date_window"}
        if set(operand) not in legacy_shapes and not (
            set(operand).issubset(structured_keys)
            and "domain" in operand
            and ("match" in operand or "date_window" in operand)
        ):
            raise MonitoringProtocolRuleError(
                f"{path}.{operator} must contain domain alone or domain, field "
                "and value, or use a structured domain/match/date_window shape"
            )
        domain = str(operand.get("domain", "")).strip().upper()
        if not domain:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.domain is required"
            )
        if "match" in operand:
            _validate_related_match_conditions(
                operand["match"],
                path=f"{path}.{operator}.match",
            )
        if "date_window" in operand:
            _validate_related_date_window(
                operand["date_window"],
                path=f"{path}.{operator}.date_window",
            )
    elif set(operand) != {"field", "value"}:
        raise MonitoringProtocolRuleError(
            f"{path}.{operator} must contain field and value"
        )
    field_name = str(operand.get("field", "")).strip()
    if "field" in operand and not field_name:
        raise MonitoringProtocolRuleError(f"{path}.{operator}.field is required")
    if operator in {"in", "not_in"} and not isinstance(operand.get("value"), list):
        raise MonitoringProtocolRuleError(
            f"{path}.{operator}.value must be a list"
        )
    if operator == "regex":
        pattern = str(operand.get("value", ""))
        if not pattern:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.value is required"
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise MonitoringProtocolRuleError(
                f"{path}.{operator}.value is not a valid regular expression"
            ) from exc


def _validate_distinct_fields(operand: Mapping[str, Any], *, path: str) -> None:
    field_name = str(operand.get("field", "")).strip()
    other_field = str(operand.get("other_field", "")).strip()
    if not field_name or not other_field:
        raise MonitoringProtocolRuleError(
            f"{path} requires field and other_field"
        )
    if field_name == other_field:
        raise MonitoringProtocolRuleError(
            f"{path} requires two different fields"
        )


def _validate_numeric_range(
    operand: Mapping[str, Any],
    *,
    minimum_key: str,
    maximum_key: str,
    path: str,
    require_both: bool = False,
) -> None:
    present = [key for key in (minimum_key, maximum_key) if key in operand]
    if (require_both and len(present) != 2) or (not require_both and not present):
        raise MonitoringProtocolRuleError(
            f"{path} requires a valid numeric range"
        )
    values: dict[str, float] = {}
    for key in present:
        value = operand[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MonitoringProtocolRuleError(f"{path}.{key} must be a number")
        values[key] = float(value)
    if (
        minimum_key in values
        and maximum_key in values
        and values[minimum_key] > values[maximum_key]
    ):
        raise MonitoringProtocolRuleError(
            f"{path}.{minimum_key} cannot exceed {maximum_key}"
        )


def _validate_related_match_conditions(value: Any, *, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise MonitoringProtocolRuleError(f"{path} must be a non-empty list")
    for index, condition in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(condition, Mapping):
            raise MonitoringProtocolRuleError(f"{item_path} must be an object")
        allowed = {"related_field", "current_field", "value", "operator"}
        if not set(condition).issubset(allowed):
            raise MonitoringProtocolRuleError(
                f"{item_path} contains unsupported keys"
            )
        related_field = str(condition.get("related_field", "")).strip()
        if not related_field:
            raise MonitoringProtocolRuleError(
                f"{item_path}.related_field is required"
            )
        has_current = bool(str(condition.get("current_field", "")).strip())
        has_value = "value" in condition
        operator = str(condition.get("operator", "eq")).strip()
        if operator in {"exists", "missing"}:
            if has_current or has_value:
                raise MonitoringProtocolRuleError(
                    f"{item_path} {operator} does not accept current_field or value"
                )
        elif has_current == has_value:
            raise MonitoringProtocolRuleError(
                f"{item_path} must contain exactly one of current_field or value"
            )
        if operator not in {
            "eq",
            "ne",
            "in",
            "not_in",
            "regex",
            "exists",
            "missing",
        }:
            raise MonitoringProtocolRuleError(
                f"{item_path}.operator is not supported"
            )
        if operator in {"in", "not_in"} and not isinstance(
            condition.get("value"), list
        ):
            raise MonitoringProtocolRuleError(
                f"{item_path}.value must be a list for {operator}"
            )
        if operator == "regex":
            pattern = str(condition.get("value", ""))
            if not pattern:
                raise MonitoringProtocolRuleError(
                    f"{item_path}.value is required for regex"
                )
            try:
                re.compile(pattern)
            except re.error as exc:
                raise MonitoringProtocolRuleError(
                    f"{item_path}.value is not a valid regular expression"
                ) from exc


def _validate_related_date_window(value: Any, *, path: str) -> None:
    if not isinstance(value, Mapping):
        raise MonitoringProtocolRuleError(f"{path} must be an object")
    allowed = {
        "related_date_field",
        "current_date_field",
        "min_days",
        "max_days",
    }
    if not set(value).issubset(allowed) or not {
        "related_date_field",
        "current_date_field",
    }.issubset(value):
        raise MonitoringProtocolRuleError(
            f"{path} requires related_date_field, current_date_field and a range"
        )
    if not str(value.get("related_date_field", "")).strip() or not str(
        value.get("current_date_field", "")
    ).strip():
        raise MonitoringProtocolRuleError(f"{path} date fields are required")
    _validate_numeric_range(
        value,
        minimum_key="min_days",
        maximum_key="max_days",
        path=path,
    )


def validate_rule_clinical_compatibility(
    *,
    rule_family: str,
    clinical_domain: str,
    required_domains: Iterable[str],
) -> None:
    allowed_clinical_domains = RULE_FAMILY_CLINICAL_DOMAINS[rule_family]
    if clinical_domain not in allowed_clinical_domains:
        raise MonitoringProtocolRuleError(
            f"rule family {rule_family} is incompatible with clinical domain {clinical_domain}"
        )
    normalized_domains = frozenset(str(item).strip().upper() for item in required_domains)
    if rule_family in {"study_treatment_change", "study_treatment_adherence"}:
        if _CONCOMITANT_MEDICATION_DATA_DOMAIN in normalized_domains:
            raise MonitoringProtocolRuleError(
                "study treatment rules must not use CM"
            )
        if not normalized_domains.intersection(_STUDY_TREATMENT_DATA_DOMAINS):
            raise MonitoringProtocolRuleError(
                "study treatment rules require one of EX, EC, DA or IP"
            )
    if rule_family == "concomitant_medication_policy":
        if _CONCOMITANT_MEDICATION_DATA_DOMAIN not in normalized_domains:
            raise MonitoringProtocolRuleError(
                "concomitant medication rules require CM"
            )
        if normalized_domains.intersection(_STUDY_TREATMENT_DATA_DOMAINS):
            raise MonitoringProtocolRuleError(
                "concomitant medication rules must not use EX, EC, DA or IP"
            )
    allowed_data_domains = RULE_FAMILY_ALLOWED_DATA_DOMAINS[rule_family]
    unexpected = normalized_domains - allowed_data_domains
    if unexpected:
        raise MonitoringProtocolRuleError(
            f"rule family {rule_family} has incompatible data domains: {sorted(unexpected)}"
        )
    for required_group in RULE_FAMILY_REQUIRED_DATA_DOMAIN_GROUPS.get(rule_family, ()):
        if not normalized_domains.intersection(required_group):
            raise MonitoringProtocolRuleError(
                f"rule family {rule_family} requires one of data domains: {sorted(required_group)}"
            )


def validate_rule_field_lineage(
    *,
    field_lineage: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    trigger_expression: Mapping[str, Any],
    exclusions: Mapping[str, Any],
    evidence_template: str,
    required_domains: Iterable[str],
) -> dict[str, Any]:
    """Validate canonical raw-field provenance for a strict lifecycle rule."""

    canonical = _validate_mapping(field_lineage, "field_lineage")
    if not canonical:
        raise MonitoringProtocolRuleError(
            "strict rule lifecycle requires canonical field_lineage"
        )
    declared_domains = {
        _bounded_text(domain, "required_domain", 80).upper()
        for domain in required_domains
    }
    if not declared_domains:
        raise MonitoringProtocolRuleError(
            "field_lineage requires declared source domains"
        )

    normalized: dict[str, dict[str, Any]] = {}
    fields_to_roles: dict[tuple[str, str], list[str]] = {}
    for raw_role, raw_binding in canonical.items():
        role = str(raw_role or "").strip()
        if not _LINEAGE_ROLE_RE.fullmatch(role):
            raise MonitoringProtocolRuleError(
                f"invalid canonical field lineage role: {role}"
            )
        if not isinstance(raw_binding, Mapping) or set(raw_binding) != {
            "field",
            "domain",
            "lineage",
        }:
            raise MonitoringProtocolRuleError(
                f"field lineage role {role} must contain field, domain and lineage"
            )
        field_name = _bounded_text(raw_binding.get("field"), f"{role}.field", 240)
        normalized_field = unicodedata.normalize("NFKC", field_name).lower()
        if any(marker in normalized_field for marker in _LINEAGE_CONCLUSION_MARKERS):
            raise MonitoringProtocolRuleError(
                f"field lineage role {role} uses a prohibited conclusion field"
            )
        domain = _bounded_text(raw_binding.get("domain"), f"{role}.domain", 80).upper()
        if domain not in declared_domains:
            raise MonitoringProtocolRuleError(
                f"field lineage role {role} belongs to undeclared domain {domain}"
            )
        lineage = _validate_canonical_lineage_header(
            raw_binding.get("lineage"),
            role=role,
        )
        normalized[role] = {
            "field": field_name,
            "domain": domain,
            "lineage": lineage,
        }
        fields_to_roles.setdefault((domain, field_name), []).append(role)

    for role, binding in normalized.items():
        lineage = binding["lineage"]
        if lineage["source_type"] != "auditable_base_value":
            continue
        input_roles = tuple(lineage["input_field_roles"])
        for input_role in input_roles:
            input_binding = normalized.get(input_role)
            if input_binding is None:
                raise MonitoringProtocolRuleError(
                    f"field lineage role {role} references unknown raw input role "
                    f"{input_role}"
                )
            if input_binding["lineage"]["source_type"] != "raw_listing_field":
                raise MonitoringProtocolRuleError(
                    f"field lineage role {role} inputs must be raw listing fields"
                )
        lineage = _normalize_canonical_unit_contract(
            lineage,
            role=role,
            input_roles=input_roles,
            normalized_bindings=normalized,
        )
        normalized[role]["lineage"] = lineage
        _validate_canonical_calculation(
            lineage["calculation_expression"],
            input_roles=input_roles,
            role=role,
            unit_field_role=lineage.get("unit_field_role"),
        )

    duplicate_fields = {
        f"{domain}.{field_name}": roles
        for (domain, field_name), roles in fields_to_roles.items()
        if len(roles) != 1
    }
    if duplicate_fields:
        raise MonitoringProtocolRuleError(
            "field_lineage requires one canonical role per output field: "
            f"{duplicate_fields}"
        )

    used_fields: set[str] = set()
    for expression in (preconditions, trigger_expression, exclusions):
        used_fields.update(_predicate_field_names(expression))
    used_fields.update(
        re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", evidence_template)
    )
    declared_field_names = {
        field_name for _domain, field_name in fields_to_roles
    }
    missing = sorted(
        field for field in used_fields if field not in declared_field_names
    )
    if missing:
        raise MonitoringProtocolRuleError(
            f"field_lineage does not cover expression/evidence fields: {missing}"
        )
    if isinstance(field_lineage, dict):
        # Legacy persisted rules are normalized in memory only. Historical
        # revisions remain byte-for-byte unchanged in storage.
        field_lineage.clear()
        field_lineage.update(json.loads(_canonical_json(normalized)))
    return normalized


def _validate_canonical_lineage_header(
    value: Any,
    *,
    role: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} requires a lineage object"
        )
    source_type = _bounded_text(
        value.get("source_type"),
        f"{role}.lineage.source_type",
        80,
    ).lower()
    if source_type in _LINEAGE_PROHIBITED_SOURCE_TYPES:
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} uses prohibited source_type {source_type}"
        )
    if source_type not in _LINEAGE_ALLOWED_SOURCE_TYPES:
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} source_type must be raw_listing_field "
            "or auditable_base_value"
        )
    locator = _bounded_text(
        value.get("source_locator"),
        f"{role}.lineage.source_locator",
        1_000,
    )
    locator_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", locator.lower())
        if token
    }
    if "row" in locator_tokens:
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} source_locator must be stable, not row-scoped"
        )
    if source_type == "raw_listing_field":
        if set(value) != {"source_type", "source_locator"}:
            raise MonitoringProtocolRuleError(
                f"raw field lineage role {role} must contain only source_type "
                "and source_locator"
            )
        if "header" not in locator_tokens:
            raise MonitoringProtocolRuleError(
                f"raw field lineage role {role} must identify a stable header locator"
            )
        return {
            "source_type": source_type,
            "source_locator": locator,
        }

    common = {
        "source_type",
        "input_field_roles",
        "calculation_expression",
        "source_locator",
    }
    unit_keys = {"unit_literal", "unit_field_role", "unit"}.intersection(value)
    if len(unit_keys) != 1 or set(value) != common.union(unit_keys):
        raise MonitoringProtocolRuleError(
            f"auditable base lineage role {role} requires raw inputs, "
            "calculation_expression, source_locator and exactly one of "
            "unit_literal or unit_field_role"
        )
    raw_input_roles = value.get("input_field_roles")
    if not isinstance(raw_input_roles, (list, tuple)) or not raw_input_roles:
        raise MonitoringProtocolRuleError(
            f"auditable base lineage role {role} requires raw input roles"
        )
    input_roles = tuple(str(item or "").strip() for item in raw_input_roles)
    if (
        any(not _LINEAGE_ROLE_RE.fullmatch(item) for item in input_roles)
        or len(set(input_roles)) != len(input_roles)
        or role in input_roles
    ):
        raise MonitoringProtocolRuleError(
            f"auditable base lineage role {role} has invalid input roles"
        )
    normalized = {
        "source_type": source_type,
        "input_field_roles": list(input_roles),
        "calculation_expression": _bounded_text(
            value.get("calculation_expression"),
            f"{role}.lineage.calculation_expression",
            2_000,
        ),
        "source_locator": locator,
    }
    unit_key = next(iter(unit_keys))
    normalized[unit_key] = _bounded_text(
        value.get(unit_key),
        f"{role}.lineage.{unit_key}",
        160,
    )
    return normalized


def _normalize_canonical_unit_contract(
    lineage: Mapping[str, Any],
    *,
    role: str,
    input_roles: tuple[str, ...],
    normalized_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    normalized = dict(lineage)
    if "unit" in normalized:
        legacy_unit = str(normalized.pop("unit"))
        if legacy_unit in input_roles:
            normalized["unit_field_role"] = legacy_unit
        else:
            matching_roles = [
                input_role
                for input_role in input_roles
                if str(normalized_bindings[input_role]["field"]) == legacy_unit
            ]
            if len(matching_roles) == 1:
                normalized["unit_field_role"] = matching_roles[0]
            else:
                normalized["unit_literal"] = legacy_unit

    unit_field_role = normalized.get("unit_field_role")
    if unit_field_role is None:
        return normalized
    unit_field_role = str(unit_field_role)
    if unit_field_role not in input_roles:
        raise MonitoringProtocolRuleError(
            f"auditable base lineage role {role} unit_field_role must reference "
            "one of its input_field_roles"
        )
    unit_binding = normalized_bindings.get(unit_field_role)
    if (
        unit_binding is None
        or unit_binding["lineage"]["source_type"] != "raw_listing_field"
    ):
        raise MonitoringProtocolRuleError(
            f"auditable base lineage role {role} unit_field_role must reference "
            "a raw listing field role"
        )
    return normalized


def normalize_rule_field_lineage_units(
    field_lineage: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize only derived-unit lineage for read-time authority checks."""

    canonical = _validate_mapping(field_lineage, "field_lineage")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_role, raw_binding in canonical.items():
        role = str(raw_role or "").strip()
        if not _LINEAGE_ROLE_RE.fullmatch(role):
            raise MonitoringProtocolRuleError(
                f"invalid canonical field lineage role: {role}"
            )
        if not isinstance(raw_binding, Mapping) or set(raw_binding) != {
            "field",
            "domain",
            "lineage",
        }:
            raise MonitoringProtocolRuleError(
                f"field lineage role {role} must contain field, domain and lineage"
            )
        normalized[role] = {
            "field": _bounded_text(raw_binding.get("field"), f"{role}.field", 240),
            "domain": _bounded_text(
                raw_binding.get("domain"), f"{role}.domain", 80
            ).upper(),
            "lineage": _validate_canonical_lineage_header(
                raw_binding.get("lineage"),
                role=role,
            ),
        }

    for role, binding in normalized.items():
        lineage = binding["lineage"]
        if lineage["source_type"] != "auditable_base_value":
            continue
        input_roles = tuple(lineage["input_field_roles"])
        for input_role in input_roles:
            input_binding = normalized.get(input_role)
            if (
                input_binding is None
                or input_binding["lineage"]["source_type"]
                != "raw_listing_field"
            ):
                raise MonitoringProtocolRuleError(
                    f"field lineage role {role} inputs must be raw listing fields"
                )
        normalized[role]["lineage"] = _normalize_canonical_unit_contract(
            lineage,
            role=role,
            input_roles=input_roles,
            normalized_bindings=normalized,
        )

    if isinstance(field_lineage, dict):
        field_lineage.clear()
        field_lineage.update(json.loads(_canonical_json(normalized)))
    return normalized


def _validate_canonical_calculation(
    expression: str,
    *,
    input_roles: tuple[str, ...],
    role: str,
    unit_field_role: Optional[str] = None,
) -> None:
    if not _LINEAGE_CALCULATION_RE.fullmatch(expression):
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} calculation is not deterministic DSL"
        )
    identifiers = set(_LINEAGE_CALCULATION_IDENTIFIER_RE.findall(expression))
    unknown = identifiers - set(input_roles) - set(
        _LINEAGE_DETERMINISTIC_FUNCTIONS
    )
    required_calculation_roles = set(input_roles)
    if unit_field_role:
        required_calculation_roles.discard(unit_field_role)
    missing = required_calculation_roles - identifiers
    if unknown or missing:
        raise MonitoringProtocolRuleError(
            f"field lineage role {role} calculation must use exactly its raw "
            f"input roles; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _predicate_field_names(value: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _PREDICATE_FIELD_KEYS:
                field_name = str(item or "").strip()
                if field_name:
                    fields.add(field_name)
            else:
                fields.update(_predicate_field_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            fields.update(_predicate_field_names(item))
    return fields


@dataclass(frozen=True)
class ProtocolSourceVersion:
    protocol_version_id: str
    project_id: str
    protocol_code: str
    version_label: str
    version_date: str
    source_entry_id: str
    source_title: str
    content_sha256: str
    status: str = "confirmed"
    applicability_status: str = "version_date_only"
    operational_effective_from: str = ""
    operational_effective_to: str = ""
    predecessor_version_id: str = ""
    amendment_source_entry_id: str = ""
    state_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        protocol_code: str,
        version_label: str,
        version_date: str,
        source_entry_id: str,
        source_title: str,
        content_sha256: str,
        status: str = "confirmed",
        applicability_status: str = "version_date_only",
        operational_effective_from: str = "",
        operational_effective_to: str = "",
        predecessor_version_id: str = "",
        amendment_source_entry_id: str = "",
    ) -> "ProtocolSourceVersion":
        project_id = _bounded_text(project_id, "project_id", 160)
        protocol_code = _bounded_text(protocol_code, "protocol_code", 160)
        version_label = _bounded_text(version_label, "version_label", 80)
        version_date = _normalize_date(version_date, "version_date", required=True)
        source_entry_id = _bounded_text(source_entry_id, "source_entry_id", 200)
        source_title = _bounded_text(source_title, "source_title", 500)
        if not isinstance(content_sha256, str) or not re.fullmatch(
            r"^[0-9a-f]{64}$", content_sha256
        ):
            raise MonitoringProtocolRuleError("content_sha256 must be a SHA-256 digest")
        status = _validate_enum(status, "status", PROTOCOL_VERSION_STATUSES)
        applicability_status = _validate_enum(
            applicability_status,
            "applicability_status",
            PROTOCOL_APPLICABILITY_STATUSES,
        )
        operational_effective_from = _normalize_date(
            operational_effective_from,
            "operational_effective_from",
        )
        operational_effective_to = _normalize_date(
            operational_effective_to,
            "operational_effective_to",
        )
        if (
            operational_effective_from
            and operational_effective_to
            and operational_effective_to < operational_effective_from
        ):
            raise MonitoringProtocolRuleError(
                "operational_effective_to precedes operational_effective_from"
            )
        if (
            applicability_status == "project_effective_confirmed"
            and not operational_effective_from
        ):
            raise MonitoringProtocolRuleError(
                "confirmed project applicability requires operational_effective_from"
            )
        protocol_version_id = _stable_id(
            "protov",
            project_id,
            protocol_code,
            version_label,
            version_date,
            content_sha256,
        )
        return cls(
            protocol_version_id=protocol_version_id,
            project_id=project_id,
            protocol_code=protocol_code,
            version_label=version_label,
            version_date=version_date,
            source_entry_id=source_entry_id,
            source_title=source_title,
            content_sha256=content_sha256,
            status=status,
            applicability_status=applicability_status,
            operational_effective_from=operational_effective_from,
            operational_effective_to=operational_effective_to,
            predecessor_version_id=_optional_text(predecessor_version_id, 200),
            amendment_source_entry_id=_optional_text(amendment_source_entry_id, 200),
            state_version=1,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("content_sha256", None)
        return value


@dataclass(frozen=True)
class ProtocolApplicabilityAssignment:
    assignment_id: str
    project_id: str
    protocol_version_id: str
    centre_id: str
    subject_id: str
    operational_effective_from: str
    operational_effective_to: str
    status: str
    evidence_text: str
    evidence_source_content_sha256: str
    evidence_source_entry_id: str
    evidence_locator: str
    created_by: str
    state_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        protocol_version_id: str,
        centre_id: str,
        operational_effective_from: str,
        operational_effective_to: str,
        evidence_text: str,
        evidence_source_content_sha256: str,
        evidence_source_entry_id: str,
        evidence_locator: str,
        created_by: str,
        subject_id: str = "",
    ) -> "ProtocolApplicabilityAssignment":
        project_id = _exact_identifier(project_id, "project_id")
        protocol_version_id = _exact_identifier(
            protocol_version_id, "protocol_version_id", 200
        )
        centre_id = _exact_identifier(centre_id, "centre_id")
        subject_id = str(subject_id or "").strip()
        if len(subject_id) > 160:
            raise MonitoringProtocolRuleError(
                "subject_id exceeds 160 characters"
            )
        operational_effective_from = _normalize_date(
            operational_effective_from,
            "operational_effective_from",
            required=True,
        )
        operational_effective_to = _normalize_date(
            operational_effective_to,
            "operational_effective_to",
            required=True,
        )
        if operational_effective_to < operational_effective_from:
            raise MonitoringProtocolRuleError(
                "operational_effective_to precedes operational_effective_from"
            )
        evidence_text = _bounded_text(evidence_text, "evidence_text", 20_000)
        if not isinstance(evidence_source_content_sha256, str) or re.fullmatch(
            r"^[0-9a-f]{64}$", evidence_source_content_sha256
        ) is None:
            raise MonitoringProtocolRuleError(
                "evidence_source_content_sha256 must be a canonical lowercase SHA-256 digest"
            )
        evidence_source_entry_id = _bounded_text(
            evidence_source_entry_id,
            "evidence_source_entry_id",
            200,
        )
        evidence_locator = _bounded_text(
            evidence_locator,
            "evidence_locator",
            1_000,
        )
        created_by = _bounded_text(created_by, "created_by", 160)
        assignment_id = _stable_id(
            "protoapp",
            project_id,
            protocol_version_id,
            centre_id,
            subject_id,
            operational_effective_from,
            operational_effective_to,
            evidence_text,
            evidence_source_content_sha256,
            evidence_source_entry_id,
            evidence_locator,
        )
        return cls(
            assignment_id=assignment_id,
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            centre_id=centre_id,
            subject_id=subject_id,
            operational_effective_from=operational_effective_from,
            operational_effective_to=operational_effective_to,
            status="candidate",
            evidence_text=evidence_text,
            evidence_source_content_sha256=evidence_source_content_sha256,
            evidence_source_entry_id=evidence_source_entry_id,
            evidence_locator=evidence_locator,
            created_by=created_by,
            state_version=1,
        )

    @property
    def scope_type(self) -> str:
        return "subject" if self.subject_id else "centre"

    def public_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "project_id": self.project_id,
            "protocol_version_id": self.protocol_version_id,
            "scope_type": self.scope_type,
            "centre_id": self.centre_id,
            "subject_id": self.subject_id,
            "operational_effective_from": self.operational_effective_from,
            "operational_effective_to": self.operational_effective_to,
            "status": self.status,
            "evidence_text": self.evidence_text,
            "evidence_source_entry_id": self.evidence_source_entry_id,
            "evidence_locator": self.evidence_locator,
            "created_by": self.created_by,
            "state_version": self.state_version,
        }


@dataclass(frozen=True)
class ProtocolApplicabilityResolution:
    resolved: bool
    diagnostic_code: str
    diagnostic_message: str
    project_id: str
    centre_id: str
    subject_id: str
    event_date: str
    protocol_version_id: str = ""
    assignment: Optional[ProtocolApplicabilityAssignment] = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "diagnostic_code": self.diagnostic_code,
            "diagnostic_message": self.diagnostic_message,
            "project_id": self.project_id,
            "centre_id": self.centre_id,
            "subject_id": self.subject_id,
            "event_date": self.event_date,
            "protocol_version_id": self.protocol_version_id,
            "assignment": (
                self.assignment.public_dict()
                if self.assignment is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ProtocolFact:
    fact_revision_id: str
    project_id: str
    protocol_version_id: str
    fact_key: str
    fact_type: str
    status: str
    title: str
    normalized_payload: dict[str, Any]
    source_entry_id: str
    source_locator: str
    source_text: str
    source_text_sha256: str
    applicability: dict[str, Any] = field(default_factory=dict)
    supersedes_fact_revision_id: str = ""
    clinical_domain: str = ""
    state_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        protocol_version_id: str,
        fact_key: str,
        fact_type: str,
        status: str,
        title: str,
        normalized_payload: Mapping[str, Any],
        source_entry_id: str,
        source_locator: str,
        source_text: str,
        applicability: Mapping[str, Any] | None = None,
        supersedes_fact_revision_id: str = "",
        clinical_domain: str = "",
    ) -> "ProtocolFact":
        project_id = _bounded_text(project_id, "project_id", 160)
        protocol_version_id = _bounded_text(
            protocol_version_id, "protocol_version_id", 200
        )
        fact_key = _normalize_key(fact_key, "fact_key")
        fact_type = _validate_enum(fact_type, "fact_type", PROTOCOL_FACT_TYPES)
        inferred_clinical_domain = FACT_TYPE_CLINICAL_DOMAIN[fact_type]
        clinical_domain = (
            _validate_enum(clinical_domain, "clinical_domain", CLINICAL_DOMAINS)
            if clinical_domain
            else inferred_clinical_domain
        )
        if clinical_domain != inferred_clinical_domain:
            raise MonitoringProtocolRuleError(
                f"fact type {fact_type} is incompatible with clinical domain {clinical_domain}"
            )
        status = _validate_enum(status, "status", PROTOCOL_FACT_STATUSES)
        title = _bounded_text(title, "title", 500)
        payload = _validate_mapping(normalized_payload, "normalized_payload")
        source_entry_id = _bounded_text(source_entry_id, "source_entry_id", 200)
        source_locator = _bounded_text(source_locator, "source_locator", 500)
        source_text = _bounded_text(source_text, "source_text", 50_000)
        applicability_value = _validate_mapping(
            applicability or {}, "applicability"
        )
        source_text_sha256 = sha256(source_text.encode("utf-8")).hexdigest()
        fact_revision_id = _stable_id(
            "protfact",
            project_id,
            protocol_version_id,
            fact_key,
            fact_type,
            _canonical_json(payload),
            source_entry_id,
            source_locator,
            source_text_sha256,
        )
        return cls(
            fact_revision_id=fact_revision_id,
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            fact_key=fact_key,
            fact_type=fact_type,
            status=status,
            title=title,
            normalized_payload=payload,
            source_entry_id=source_entry_id,
            source_locator=source_locator,
            source_text=source_text,
            source_text_sha256=source_text_sha256,
            applicability=applicability_value,
            supersedes_fact_revision_id=_optional_text(
                supersedes_fact_revision_id, 200
            ),
            clinical_domain=clinical_domain,
            state_version=1,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("source_text_sha256", None)
        source_text = value.pop("source_text")
        source_entry_id = value.pop("source_entry_id")
        source_locator = value.pop("source_locator")
        value["source_text"] = source_text
        value["source_entry_id"] = source_entry_id
        value["source_locator"] = source_locator
        return value


@dataclass(frozen=True)
class RuleSourceReference:
    fact_revision_id: str
    source_entry_id: str
    source_locator: str
    source_text: str
    source_text_sha256: str

    @classmethod
    def create(
        cls,
        *,
        fact_revision_id: str,
        source_entry_id: str,
        source_locator: str,
        source_text: str,
        source_text_sha256: str = "",
    ) -> "RuleSourceReference":
        source_text = _bounded_text(source_text, "source_text", 50_000)
        calculated_sha256 = sha256(source_text.encode("utf-8")).hexdigest()
        supplied_sha256 = source_text_sha256
        if supplied_sha256 and (
            not isinstance(supplied_sha256, str)
            or re.fullmatch(r"^[0-9a-f]{64}$", supplied_sha256) is None
        ):
            raise MonitoringProtocolRuleError(
                "source_text_sha256 must be a canonical lowercase SHA-256 digest"
            )
        if supplied_sha256 and supplied_sha256 != calculated_sha256:
            raise MonitoringProtocolRuleError(
                "source_text_sha256 does not match source_text"
            )
        return cls(
            fact_revision_id=_bounded_text(
                fact_revision_id, "fact_revision_id", 200
            ),
            source_entry_id=_bounded_text(source_entry_id, "source_entry_id", 200),
            source_locator=_bounded_text(source_locator, "source_locator", 500),
            source_text=source_text,
            source_text_sha256=calculated_sha256,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("source_text_sha256", None)
        source_text = value.pop("source_text")
        source_entry_id = value.pop("source_entry_id")
        source_locator = value.pop("source_locator")
        value["source_text"] = source_text
        value["source_entry_id"] = source_entry_id
        value["source_locator"] = source_locator
        return value


_RULE_IDENTITY_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RULE_IDENTITY_REQUIRED_FIELDS = (
    "mapping_revision",
    "mapping_content_sha256",
    "capability_manifest_sha256",
)


def _validate_rule_identity(
    *,
    mapping_revision: Any,
    mapping_content_sha256: Any,
    capability_manifest_sha256: Any,
    effective_capabilities_sha256: Any,
    recommendation_candidate_id: Any,
) -> dict[str, str]:
    """Fail closed on partial or malformed immutable rule identity material."""

    def _sha256_field(value: Any, field_name: str) -> str:
        if value is None or value == "":
            return ""
        if not isinstance(value, str) or not _RULE_IDENTITY_SHA256_RE.fullmatch(
            value
        ):
            raise MonitoringProtocolRuleError(
                f"{field_name} must be a lowercase sha256 hex digest"
            )
        return value

    identity = {
        "mapping_revision": str(mapping_revision or "").strip(),
        "mapping_content_sha256": _sha256_field(
            mapping_content_sha256, "mapping_content_sha256"
        ),
        "capability_manifest_sha256": _sha256_field(
            capability_manifest_sha256, "capability_manifest_sha256"
        ),
        "effective_capabilities_sha256": _sha256_field(
            effective_capabilities_sha256, "effective_capabilities_sha256"
        ),
        "recommendation_candidate_id": str(
            recommendation_candidate_id or ""
        ).strip(),
    }
    if any(identity.values()):
        missing = [
            field_name
            for field_name in _RULE_IDENTITY_REQUIRED_FIELDS
            if not identity[field_name]
        ]
        if missing:
            raise MonitoringProtocolRuleError(
                "partial rule identity is not allowed; "
                f"missing {', '.join(missing)}"
            )
    return identity


@dataclass(frozen=True)
class MonitoringRuleDefinition:
    rule_revision_id: str
    project_id: str
    protocol_version_id: str
    rule_key: str
    rule_family: str
    status: str
    title: str
    executor: str
    required_domains: tuple[str, ...]
    preconditions: dict[str, Any]
    trigger_expression: dict[str, Any]
    exclusions: dict[str, Any]
    severity: str
    confidence: str
    evidence_template: str
    fact_revision_ids: tuple[str, ...]
    source_entry_id: str
    source_locator: str
    source_text: str
    source_text_sha256: str
    supersedes_rule_revision_id: str = ""
    clinical_domain: str = ""
    source_refs: tuple[RuleSourceReference, ...] = ()
    field_lineage: dict[str, Any] = field(default_factory=dict)
    state_version: int = 1
    mapping_revision: str = ""
    mapping_content_sha256: str = ""
    capability_manifest_sha256: str = ""
    effective_capabilities_sha256: str = ""
    recommendation_candidate_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        protocol_version_id: str,
        rule_key: str,
        rule_family: str,
        status: str,
        title: str,
        executor: str,
        required_domains: Iterable[str],
        preconditions: Mapping[str, Any],
        trigger_expression: Mapping[str, Any],
        exclusions: Mapping[str, Any],
        severity: str,
        confidence: str,
        evidence_template: str,
        fact_revision_ids: Iterable[str],
        source_entry_id: str,
        source_locator: str,
        source_text: str,
        supersedes_rule_revision_id: str = "",
        clinical_domain: str = "",
        source_refs: Iterable[RuleSourceReference | Mapping[str, Any]] = (),
        field_lineage: Optional[Mapping[str, Any]] = None,
        mapping_revision: str = "",
        mapping_content_sha256: str = "",
        capability_manifest_sha256: str = "",
        effective_capabilities_sha256: str = "",
        recommendation_candidate_id: str = "",
    ) -> "MonitoringRuleDefinition":
        project_id = _bounded_text(project_id, "project_id", 160)
        protocol_version_id = _bounded_text(
            protocol_version_id, "protocol_version_id", 200
        )
        rule_key = _normalize_key(rule_key, "rule_key")
        rule_family = _validate_enum(
            rule_family,
            "rule_family",
            ALL_RULE_FAMILIES,
        )
        inferred_clinical_domains = RULE_FAMILY_CLINICAL_DOMAINS[rule_family]
        if clinical_domain:
            clinical_domain = _validate_enum(
                clinical_domain, "clinical_domain", CLINICAL_DOMAINS
            )
        elif len(inferred_clinical_domains) == 1:
            clinical_domain = next(iter(inferred_clinical_domains))
        else:
            raise MonitoringProtocolRuleError(
                "cross-domain rules require an explicit clinical_domain"
            )
        status = _validate_enum(status, "status", RULE_STATUSES)
        title = _bounded_text(title, "title", 500)
        executor = _validate_enum(executor, "executor", RULE_EXECUTORS)
        required_domains_value = tuple(
            sorted(
                {
                    _bounded_text(domain, "required_domain", 80).upper()
                    for domain in required_domains
                }
            )
        )
        if status == "enabled" and not required_domains_value:
            raise MonitoringProtocolRuleError(
                "enabled rules require at least one source domain"
            )
        validate_rule_clinical_compatibility(
            rule_family=rule_family,
            clinical_domain=clinical_domain,
            required_domains=required_domains_value,
        )
        preconditions_value = validate_predicate_expression(preconditions)
        trigger_value = validate_predicate_expression(trigger_expression)
        exclusions_value = validate_predicate_expression(exclusions)
        severity = _validate_enum(severity, "severity", RULE_SEVERITIES)
        confidence = _validate_enum(
            confidence,
            "confidence",
            RULE_CONFIDENCE_LEVELS,
        )
        evidence_template = _bounded_text(
            evidence_template, "evidence_template", 4_000
        )
        fact_revision_ids_value = tuple(
            sorted(
                {
                    _bounded_text(item, "fact_revision_id", 200)
                    for item in fact_revision_ids
                }
            )
        )
        if not fact_revision_ids_value:
            raise MonitoringProtocolRuleError(
                "rule must bind at least one protocol fact revision"
            )
        source_entry_id = _bounded_text(source_entry_id, "source_entry_id", 200)
        source_locator = _bounded_text(source_locator, "source_locator", 500)
        source_text = _bounded_text(source_text, "source_text", 50_000)
        source_text_sha256 = sha256(source_text.encode("utf-8")).hexdigest()
        source_refs_value: list[RuleSourceReference] = []
        for item in source_refs:
            if isinstance(item, RuleSourceReference):
                source_refs_value.append(item)
            elif isinstance(item, Mapping):
                source_refs_value.append(RuleSourceReference.create(**dict(item)))
            else:
                raise MonitoringProtocolRuleError(
                    "source_refs must contain source reference objects"
                )
        if not source_refs_value:
            source_refs_value = [
                RuleSourceReference.create(
                    fact_revision_id=fact_revision_id,
                    source_entry_id=source_entry_id,
                    source_locator=source_locator,
                    source_text=source_text,
                )
                for fact_revision_id in fact_revision_ids_value
            ]
        source_refs_tuple = tuple(
            sorted(source_refs_value, key=lambda item: item.fact_revision_id)
        )
        if {item.fact_revision_id for item in source_refs_tuple} != set(
            fact_revision_ids_value
        ):
            raise MonitoringProtocolRuleError(
                "source_refs must bind every and only referenced fact revision"
            )
        if len({item.fact_revision_id for item in source_refs_tuple}) != len(
            source_refs_tuple
        ):
            raise MonitoringProtocolRuleError(
                "source_refs contains duplicate fact bindings"
            )
        primary_ref = source_refs_tuple[0]
        if (
            primary_ref.source_entry_id != source_entry_id
            or primary_ref.source_locator != source_locator
            or primary_ref.source_text_sha256 != source_text_sha256
        ):
            raise MonitoringProtocolRuleError(
                "legacy primary source must match the first source_refs entry"
            )
        field_lineage_value = _validate_mapping(
            field_lineage or {},
            "field_lineage",
        )
        identity_values = _validate_rule_identity(
            mapping_revision=mapping_revision,
            mapping_content_sha256=mapping_content_sha256,
            capability_manifest_sha256=capability_manifest_sha256,
            effective_capabilities_sha256=effective_capabilities_sha256,
            recommendation_candidate_id=recommendation_candidate_id,
        )
        revision_parts: list[Any] = [
            project_id,
            protocol_version_id,
            rule_key,
            rule_family,
            executor,
            required_domains_value,
            _canonical_json(preconditions_value),
            _canonical_json(trigger_value),
            _canonical_json(exclusions_value),
            severity,
            confidence,
            fact_revision_ids_value,
            tuple(asdict(item) for item in source_refs_tuple),
        ]
        if field_lineage_value:
            revision_parts.append(_canonical_json(field_lineage_value))
        if any(identity_values.values()):
            revision_parts.append(_canonical_json(identity_values))
        rule_revision_id = _stable_id("monrule", *revision_parts)
        return cls(
            rule_revision_id=rule_revision_id,
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            rule_key=rule_key,
            rule_family=rule_family,
            status=status,
            title=title,
            executor=executor,
            required_domains=required_domains_value,
            preconditions=preconditions_value,
            trigger_expression=trigger_value,
            exclusions=exclusions_value,
            severity=severity,
            confidence=confidence,
            evidence_template=evidence_template,
            fact_revision_ids=fact_revision_ids_value,
            source_entry_id=source_entry_id,
            source_locator=source_locator,
            source_text=source_text,
            source_text_sha256=source_text_sha256,
            supersedes_rule_revision_id=_optional_text(
                supersedes_rule_revision_id, 200
            ),
            clinical_domain=clinical_domain,
            source_refs=source_refs_tuple,
            field_lineage=field_lineage_value,
            state_version=1,
            **identity_values,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("source_text_sha256", None)
        source_text = value.pop("source_text")
        source_entry_id = value.pop("source_entry_id")
        source_locator = value.pop("source_locator")
        value["required_domains"] = list(self.required_domains)
        value["fact_revision_ids"] = list(self.fact_revision_ids)
        value["source_refs"] = [item.public_dict() for item in self.source_refs]
        value["source_text"] = source_text
        value["source_entry_id"] = source_entry_id
        value["source_locator"] = source_locator
        for identity_field in (
            "mapping_revision",
            "mapping_content_sha256",
            "capability_manifest_sha256",
            "effective_capabilities_sha256",
            "recommendation_candidate_id",
        ):
            if not value[identity_field]:
                value.pop(identity_field)
        return value

    def semantic_fingerprint(self) -> str:
        """Compare medical logic across protocol versions without locator churn."""
        payload = {
            "rule_key": self.rule_key,
            "rule_family": self.rule_family,
            "clinical_domain": self.clinical_domain,
            "title": self.title,
            "executor": self.executor,
            "required_domains": self.required_domains,
            "preconditions": self.preconditions,
            "trigger_expression": self.trigger_expression,
            "exclusions": self.exclusions,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence_template": self.evidence_template,
            "source_text_sha256": self.source_text_sha256,
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonitoringRulePack:
    rule_pack_id: str
    project_id: str
    protocol_version_id: str
    pack_revision: int
    status: str
    applicability_status: str
    rule_revision_ids: tuple[str, ...]
    content_sha256: str
    created_by: str
    retrospective_policy: str = "open_risks_only"
    published_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        protocol_version_id: str,
        pack_revision: int,
        status: str,
        applicability_status: str,
        rules: Sequence[MonitoringRuleDefinition],
        created_by: str,
        retrospective_policy: str = "open_risks_only",
        published_at: str = "",
        _lifecycle_authorized: bool = False,
    ) -> "MonitoringRulePack":
        project_id = _bounded_text(project_id, "project_id", 160)
        protocol_version_id = _bounded_text(
            protocol_version_id, "protocol_version_id", 200
        )
        if int(pack_revision) < 1:
            raise MonitoringProtocolRuleError("pack_revision must be at least 1")
        status = _validate_enum(status, "status", RULE_PACK_STATUSES)
        if status != "draft" and not _lifecycle_authorized:
            raise MonitoringProtocolRuleError(
                "non-draft rule pack stages require MonitoringRuleLifecycleService"
            )
        applicability_status = _validate_enum(
            applicability_status,
            "applicability_status",
            PROTOCOL_APPLICABILITY_STATUSES,
        )
        if not rules:
            raise MonitoringProtocolRuleError("rule pack requires at least one rule")
        rule_revision_ids = tuple(sorted({rule.rule_revision_id for rule in rules}))
        if len(rule_revision_ids) != len(rules):
            raise MonitoringProtocolRuleError("rule pack contains duplicate rules")
        if any(rule.project_id != project_id for rule in rules):
            raise MonitoringProtocolRuleError("rule pack contains another project")
        if any(rule.protocol_version_id != protocol_version_id for rule in rules):
            raise MonitoringProtocolRuleError(
                "rule pack contains another protocol version"
            )
        if status == "published" and any(rule.status != "enabled" for rule in rules):
            raise MonitoringProtocolRuleError(
                "published rule pack may contain only enabled rules"
            )
        retrospective_policy = _validate_enum(
            retrospective_policy,
            "retrospective_policy",
            RETROSPECTIVE_POLICIES,
        )
        content_sha256 = sha256(
            _canonical_json(
                [rule.public_dict() for rule in sorted(rules, key=lambda item: item.rule_key)]
            ).encode("utf-8")
        ).hexdigest()
        rule_pack_id = _stable_id(
            "monpack",
            project_id,
            protocol_version_id,
            pack_revision,
            content_sha256,
            retrospective_policy,
        )
        return cls(
            rule_pack_id=rule_pack_id,
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            pack_revision=int(pack_revision),
            status=status,
            applicability_status=applicability_status,
            rule_revision_ids=rule_revision_ids,
            content_sha256=content_sha256,
            created_by=_bounded_text(created_by, "created_by", 160),
            retrospective_policy=retrospective_policy,
            published_at=_optional_text(published_at, 80),
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("content_sha256", None)
        value["rule_revision_ids"] = list(self.rule_revision_ids)
        return value


@dataclass(frozen=True)
class RulePackImpact:
    previous_rule_pack_id: str
    current_rule_pack_id: str
    added_rule_keys: tuple[str, ...]
    changed_rule_keys: tuple[str, ...]
    superseded_rule_keys: tuple[str, ...]
    unchanged_rule_keys: tuple[str, ...]

    @property
    def re_review_rule_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(self.added_rule_keys)
                | set(self.changed_rule_keys)
                | set(self.superseded_rule_keys)
            )
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["re_review_rule_keys"] = list(self.re_review_rule_keys)
        return value


@dataclass(frozen=True)
class RuleRiskBinding:
    risk_instance_id: str
    project_id: str
    rule_key: str
    evaluated_rule_revision_id: str


@dataclass(frozen=True)
class RuleReReviewTask:
    task_id: str
    project_id: str
    risk_instance_id: str
    rule_key: str
    previous_rule_revision_id: str
    current_rule_revision_id: str
    reason: str
    status: str = "open"

    @classmethod
    def create(
        cls,
        *,
        binding: RuleRiskBinding,
        current_rule_revision_id: str,
        reason: str,
    ) -> "RuleReReviewTask":
        status = "open"
        task_id = _stable_id(
            "rulereview",
            binding.project_id,
            binding.risk_instance_id,
            binding.rule_key,
            binding.evaluated_rule_revision_id,
            current_rule_revision_id,
        )
        return cls(
            task_id=task_id,
            project_id=_bounded_text(binding.project_id, "project_id", 160),
            risk_instance_id=_bounded_text(
                binding.risk_instance_id, "risk_instance_id", 240
            ),
            rule_key=_normalize_key(binding.rule_key, "rule_key"),
            previous_rule_revision_id=_bounded_text(
                binding.evaluated_rule_revision_id,
                "evaluated_rule_revision_id",
                200,
            ),
            current_rule_revision_id=_optional_text(
                current_rule_revision_id, 200
            ),
            reason=_bounded_text(reason, "reason", 1_000),
            status=status,
        )


@dataclass(frozen=True)
class RuleGoldRecordFieldBinding:
    record_role: str
    record_field: str
    source_field: str

    @classmethod
    def create(
        cls,
        *,
        record_role: str,
        record_field: str,
        source_field: str,
    ) -> "RuleGoldRecordFieldBinding":
        return cls(
            record_role=_bounded_text(record_role, "record_role", 200),
            record_field=_bounded_text(record_field, "record_field", 200),
            source_field=_bounded_text(source_field, "source_field", 200),
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "RuleGoldRecordFieldBinding":
        return cls.create(
            record_role=value.get("record_role", ""),
            record_field=value.get("record_field", ""),
            source_field=value.get("source_field", ""),
        )


@dataclass(frozen=True)
class RuleGoldSourceRowBinding:
    business_key: str
    domain: str
    source_locator: str
    row_fingerprint: str
    record_roles: tuple[str, ...]
    field_bindings: tuple[RuleGoldRecordFieldBinding, ...]

    @classmethod
    def create(
        cls,
        *,
        business_key: str,
        domain: str,
        source_locator: str,
        row_fingerprint: str,
        record_roles: Iterable[str],
        field_bindings: Iterable[
            RuleGoldRecordFieldBinding | Mapping[str, Any]
        ],
    ) -> "RuleGoldSourceRowBinding":
        if (
            not isinstance(row_fingerprint, str)
            or _SHA256_HEX_RE.fullmatch(row_fingerprint) is None
        ):
            raise MonitoringProtocolRuleError(
                "gold source row binding requires a lowercase SHA-256 row fingerprint"
            )
        fingerprint = row_fingerprint
        roles = tuple(
            sorted(
                {
                    _bounded_text(role, "record_role", 200)
                    for role in record_roles
                }
            )
        )
        if not roles:
            raise MonitoringProtocolRuleError(
                "gold source row binding requires at least one record role"
            )
        fields = tuple(
            sorted(
                (
                    item
                    if isinstance(item, RuleGoldRecordFieldBinding)
                    else RuleGoldRecordFieldBinding.from_mapping(item)
                    for item in field_bindings
                ),
                key=lambda item: (
                    item.record_role,
                    item.record_field,
                    item.source_field,
                ),
            )
        )
        if not fields:
            raise MonitoringProtocolRuleError(
                "gold source row binding requires field-level source bindings"
            )
        if any(item.record_role not in roles for item in fields):
            raise MonitoringProtocolRuleError(
                "gold source row field binding uses an undeclared record role"
            )
        field_keys = [
            (item.record_role, item.record_field, item.source_field)
            for item in fields
        ]
        if len(field_keys) != len(set(field_keys)):
            raise MonitoringProtocolRuleError(
                "gold source row field bindings must be unique"
            )
        return cls(
            business_key=_bounded_text(business_key, "business_key", 500),
            domain=_bounded_text(domain, "domain", 80).upper(),
            source_locator=_bounded_text(
                source_locator,
                "source_locator",
                500,
            ),
            row_fingerprint=fingerprint,
            record_roles=roles,
            field_bindings=fields,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "RuleGoldSourceRowBinding":
        if not value.get("field_bindings"):
            raw_fingerprint = value.get("row_fingerprint")
            if (
                not isinstance(raw_fingerprint, str)
                or _SHA256_HEX_RE.fullmatch(raw_fingerprint) is None
            ):
                raise MonitoringProtocolRuleError(
                    "legacy gold source row binding has an invalid row fingerprint"
                )
            fingerprint = raw_fingerprint
            roles = tuple(
                sorted(
                    {
                        _bounded_text(role, "record_role", 200)
                        for role in value.get("record_roles", ())
                    }
                )
            )
            if not roles:
                raise MonitoringProtocolRuleError(
                    "legacy gold source row binding lacks record roles"
                )
            return cls(
                business_key=_bounded_text(
                    value.get("business_key", ""),
                    "business_key",
                    500,
                ),
                domain=_bounded_text(
                    value.get("domain", ""),
                    "domain",
                    80,
                ).upper(),
                source_locator=_bounded_text(
                    value.get("source_locator", ""),
                    "source_locator",
                    500,
                ),
                row_fingerprint=fingerprint,
                record_roles=roles,
                field_bindings=(),
            )
        return cls.create(
            business_key=value.get("business_key", ""),
            domain=value.get("domain", ""),
            source_locator=value.get("source_locator", ""),
            row_fingerprint=value.get("row_fingerprint", ""),
            record_roles=value.get("record_roles", ()),
            field_bindings=value.get("field_bindings", ()),
        )


def _gold_case_coverage_labels(
    values: Iterable[str] | None,
    *,
    expected_match: bool,
) -> tuple[str, ...]:
    if values is None:
        values = ("positive",) if expected_match else ("negative",)
    labels = tuple(
        sorted(
            {
                _validate_enum(
                    item,
                    "coverage_label",
                    GOLD_CASE_COVERAGE_LABELS,
                )
                for item in values
            }
        )
    )
    if not labels:
        raise MonitoringProtocolRuleError(
            "gold standard case requires coverage labels"
        )
    if "positive" in labels and "negative" in labels:
        raise MonitoringProtocolRuleError(
            "gold standard case cannot be both positive and negative"
        )
    required = "positive" if expected_match else "negative"
    prohibited = "negative" if expected_match else "positive"
    if required not in labels or prohibited in labels:
        raise MonitoringProtocolRuleError(
            f"expected_match={str(expected_match).lower()} requires {required} "
            f"and prohibits {prohibited}"
        )
    return labels


def _require_canonical_source_content_sha256(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"^[0-9a-f]{64}$", value) is None:
        raise MonitoringProtocolRuleError(
            "source_content_sha256 must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class RuleGoldStandardCase:
    case_id: str
    project_id: str
    rule_key: str
    rule_revision_id: str
    source_entry_id: str
    source_content_sha256: str
    source_revision: str
    batch_revision: str
    case_label: str
    input_record: dict[str, Any]
    previous_record: dict[str, Any]
    related_records: dict[str, list[dict[str, Any]]]
    observed_domains: tuple[str, ...]
    expected_match: bool
    coverage_labels: tuple[str, ...]
    medical_rationale: str
    evidence_locators: tuple[str, ...]
    source_row_bindings: tuple[RuleGoldSourceRowBinding, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_key: str,
        rule_revision_id: str,
        source_entry_id: str,
        source_content_sha256: str,
        source_revision: str,
        batch_revision: str,
        case_label: str,
        input_record: Mapping[str, Any],
        observed_domains: Iterable[str],
        expected_match: bool,
        medical_rationale: str,
        coverage_labels: Iterable[str] | None = None,
        previous_record: Mapping[str, Any] | None = None,
        related_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        evidence_locators: Iterable[str] = (),
        source_row_bindings: Iterable[
            RuleGoldSourceRowBinding | Mapping[str, Any]
        ] = (),
    ) -> "RuleGoldStandardCase":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_key = _normalize_key(rule_key, "rule_key")
        rule_revision_id = _bounded_text(
            rule_revision_id,
            "rule_revision_id",
            200,
        )
        source_entry_id = _bounded_text(source_entry_id, "source_entry_id", 200)
        source_content_sha256 = _require_canonical_source_content_sha256(
            source_content_sha256
        )
        source_revision = _bounded_text(source_revision, "source_revision", 200)
        batch_revision = _bounded_text(batch_revision, "batch_revision", 200)
        case_label = _bounded_text(case_label, "case_label", 500)
        input_value = _validate_mapping(input_record, "input_record")
        previous_value = _validate_mapping(previous_record or {}, "previous_record")
        related_value = {
            str(domain).strip().upper(): [
                _validate_mapping(item, "related_record") for item in records
            ]
            for domain, records in (related_records or {}).items()
        }
        observed_value = tuple(
            sorted(
                {
                    _bounded_text(item, "observed_domain", 80).upper()
                    for item in observed_domains
                }
            )
        )
        if not observed_value:
            raise MonitoringProtocolRuleError(
                "gold standard case requires observed domains"
            )
        expected_value = bool(expected_match)
        coverage_value = _gold_case_coverage_labels(
            coverage_labels,
            expected_match=expected_value,
        )
        rationale = _bounded_text(
            medical_rationale,
            "medical_rationale",
            4_000,
        )
        locators = tuple(
            sorted(
                {
                    _bounded_text(item, "evidence_locator", 500)
                    for item in evidence_locators
                }
            )
        )
        if not locators:
            raise MonitoringProtocolRuleError(
                "gold standard case requires evidence locators"
            )
        if any(source_content_sha256 not in locator for locator in locators):
            raise MonitoringProtocolRuleError(
                "gold standard case evidence locators must bind source_content_sha256"
            )
        bindings = tuple(
            sorted(
                (
                    item
                    if isinstance(item, RuleGoldSourceRowBinding)
                    else RuleGoldSourceRowBinding.from_mapping(item)
                    for item in source_row_bindings
                ),
                key=lambda item: (
                    item.source_locator,
                    item.business_key,
                    item.record_roles,
                ),
            )
        )
        binding_locators = [item.source_locator for item in bindings]
        if len(binding_locators) != len(set(binding_locators)):
            raise MonitoringProtocolRuleError(
                "gold standard case source row bindings must be unique by locator"
            )
        if bindings and set(binding_locators) != set(locators):
            raise MonitoringProtocolRuleError(
                "gold standard case source row bindings must cover evidence locators exactly"
            )
        case_id = _stable_id(
            "goldcase",
            project_id,
            rule_key,
            rule_revision_id,
            source_entry_id,
            source_content_sha256,
            source_revision,
            batch_revision,
            case_label,
            _canonical_json(input_value),
            _canonical_json(previous_value),
            _canonical_json(related_value),
            observed_value,
            expected_value,
            coverage_value,
            rationale,
            locators,
            tuple(asdict(item) for item in bindings),
        )
        return cls(
            case_id=case_id,
            project_id=project_id,
            rule_key=rule_key,
            rule_revision_id=rule_revision_id,
            source_entry_id=source_entry_id,
            source_content_sha256=source_content_sha256,
            source_revision=source_revision,
            batch_revision=batch_revision,
            case_label=case_label,
            input_record=input_value,
            previous_record=previous_value,
            related_records=related_value,
            observed_domains=observed_value,
            expected_match=expected_value,
            coverage_labels=coverage_value,
            medical_rationale=rationale,
            evidence_locators=locators,
            source_row_bindings=bindings,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observed_domains"] = list(self.observed_domains)
        value["coverage_labels"] = list(self.coverage_labels)
        value["evidence_locators"] = list(self.evidence_locators)
        value["source_row_bindings"] = [
            {
                **asdict(item),
                "record_roles": list(item.record_roles),
            }
            for item in self.source_row_bindings
        ]
        return value


def gold_case_content_sha256(case: RuleGoldStandardCase) -> str:
    payload = asdict(case)
    payload.pop("case_id", None)
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def gold_case_set_content_sha256(
    cases: Sequence[RuleGoldStandardCase],
) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "content_sha256": gold_case_content_sha256(case),
        }
        for case in sorted(cases, key=lambda item: item.case_id)
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuleDiagnosticCase:
    case_id: str
    project_id: str
    rule_key: str
    rule_revision_id: str
    source_entry_id: str
    source_content_sha256: str
    source_revision: str
    batch_revision: str
    case_label: str
    input_record: dict[str, Any]
    previous_record: dict[str, Any]
    related_records: dict[str, list[dict[str, Any]]]
    observed_domains: tuple[str, ...]
    expected_diagnostic_category: str
    expected_diagnostic_code: str
    medical_rationale: str
    evidence_locators: tuple[str, ...]
    source_row_bindings: tuple[RuleGoldSourceRowBinding, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_key: str,
        rule_revision_id: str,
        source_entry_id: str,
        source_content_sha256: str,
        source_revision: str,
        batch_revision: str,
        case_label: str,
        input_record: Mapping[str, Any],
        observed_domains: Iterable[str],
        expected_diagnostic_category: str,
        expected_diagnostic_code: str,
        medical_rationale: str,
        previous_record: Mapping[str, Any] | None = None,
        related_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        evidence_locators: Iterable[str] = (),
        source_row_bindings: Iterable[
            RuleGoldSourceRowBinding | Mapping[str, Any]
        ] = (),
    ) -> "RuleDiagnosticCase":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_key = _normalize_key(rule_key, "rule_key")
        rule_revision_id = _bounded_text(
            rule_revision_id, "rule_revision_id", 200
        )
        source_entry_id = _bounded_text(source_entry_id, "source_entry_id", 200)
        source_content_sha256 = _require_canonical_source_content_sha256(
            source_content_sha256
        )
        source_revision = _bounded_text(source_revision, "source_revision", 200)
        batch_revision = _bounded_text(batch_revision, "batch_revision", 200)
        case_label = _bounded_text(case_label, "case_label", 500)
        input_value = _validate_mapping(input_record, "input_record")
        previous_value = _validate_mapping(previous_record or {}, "previous_record")
        related_value = {
            str(domain).strip().upper(): [
                _validate_mapping(item, "related_record") for item in records
            ]
            for domain, records in (related_records or {}).items()
        }
        observed_value = tuple(
            sorted(
                {
                    _bounded_text(item, "observed_domain", 80).upper()
                    for item in observed_domains
                }
            )
        )
        if not observed_value:
            raise MonitoringProtocolRuleError(
                "diagnostic case requires observed domains"
            )
        category = _validate_enum(
            expected_diagnostic_category,
            "expected_diagnostic_category",
            DIAGNOSTIC_CASE_CATEGORIES,
        )
        code = _normalize_key(
            expected_diagnostic_code,
            "expected_diagnostic_code",
        )
        rationale = _bounded_text(
            medical_rationale, "medical_rationale", 4_000
        )
        locators = tuple(
            sorted(
                {
                    _bounded_text(item, "evidence_locator", 500)
                    for item in evidence_locators
                }
            )
        )
        if not locators:
            raise MonitoringProtocolRuleError(
                "diagnostic case requires evidence locators"
            )
        if any(source_content_sha256 not in locator for locator in locators):
            raise MonitoringProtocolRuleError(
                "diagnostic case evidence locators must bind source_content_sha256"
            )
        bindings = tuple(
            sorted(
                (
                    item
                    if isinstance(item, RuleGoldSourceRowBinding)
                    else RuleGoldSourceRowBinding.from_mapping(item)
                    for item in source_row_bindings
                ),
                key=lambda item: (
                    item.source_locator,
                    item.business_key,
                    item.record_roles,
                ),
            )
        )
        binding_locators = [item.source_locator for item in bindings]
        if len(binding_locators) != len(set(binding_locators)):
            raise MonitoringProtocolRuleError(
                "diagnostic source row bindings must be unique by locator"
            )
        if bindings and set(binding_locators) != set(locators):
            raise MonitoringProtocolRuleError(
                "diagnostic source row bindings must cover evidence locators exactly"
            )
        case_id = _stable_id(
            "diagcase",
            project_id,
            rule_key,
            rule_revision_id,
            source_entry_id,
            source_content_sha256,
            source_revision,
            batch_revision,
            case_label,
            _canonical_json(input_value),
            _canonical_json(previous_value),
            _canonical_json(related_value),
            observed_value,
            category,
            code,
            rationale,
            locators,
            tuple(asdict(item) for item in bindings),
        )
        return cls(
            case_id=case_id,
            project_id=project_id,
            rule_key=rule_key,
            rule_revision_id=rule_revision_id,
            source_entry_id=source_entry_id,
            source_content_sha256=source_content_sha256,
            source_revision=source_revision,
            batch_revision=batch_revision,
            case_label=case_label,
            input_record=input_value,
            previous_record=previous_value,
            related_records=related_value,
            observed_domains=observed_value,
            expected_diagnostic_category=category,
            expected_diagnostic_code=code,
            medical_rationale=rationale,
            evidence_locators=locators,
            source_row_bindings=bindings,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observed_domains"] = list(self.observed_domains)
        value["evidence_locators"] = list(self.evidence_locators)
        value["source_row_bindings"] = [
            {
                **asdict(item),
                "record_roles": list(item.record_roles),
            }
            for item in self.source_row_bindings
        ]
        return value


def diagnostic_case_content_sha256(case: RuleDiagnosticCase) -> str:
    payload = asdict(case)
    payload.pop("case_id", None)
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def diagnostic_case_set_content_sha256(
    cases: Sequence[RuleDiagnosticCase],
) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "content_sha256": diagnostic_case_content_sha256(case),
        }
        for case in sorted(cases, key=lambda item: item.case_id)
    ]
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuleShadowCaseResult:
    case_id: str
    rule_key: str
    rule_revision_id: str
    expected_match: bool
    actual_match: bool
    passed: bool
    evidence_summary: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool)
            for value in (self.expected_match, self.actual_match, self.passed)
        ):
            raise MonitoringProtocolRuleError(
                "shadow case expected_match, actual_match and passed must be boolean"
            )
        if self.passed and self.expected_match != self.actual_match:
            raise MonitoringProtocolRuleError(
                "shadow case cannot pass when actual_match differs from expected_match"
            )


@dataclass(frozen=True)
class RuleShadowDiagnosticResult:
    case_id: str
    rule_key: str
    rule_revision_id: str
    expected_diagnostic_category: str
    expected_diagnostic_code: str
    actual_state: str
    actual_diagnostic_code: str
    passed: bool
    evidence_summary: str

    def __post_init__(self) -> None:
        if self.actual_state not in {"true", "false", "indeterminate"}:
            raise MonitoringProtocolRuleError(
                "diagnostic shadow result has an invalid actual_state"
            )
        expected_pass = (
            self.actual_state == "indeterminate"
            and self.actual_diagnostic_code == self.expected_diagnostic_code
        )
        if self.passed != expected_pass:
            raise MonitoringProtocolRuleError(
                "diagnostic shadow pass must require indeterminate state and "
                "the exact expected diagnostic code"
            )


@dataclass(frozen=True)
class RuleRevisionCoverageSnapshot:
    rule_key: str
    rule_revision_id: str
    rule_family: str
    positive_count: int
    negative_count: int
    boundary_count: int
    diagnostic_indeterminate_count: int
    authoritative_projects: tuple[str, ...]

    def __post_init__(self) -> None:
        counts = (
            self.positive_count,
            self.negative_count,
            self.boundary_count,
            self.diagnostic_indeterminate_count,
        )
        if any(isinstance(value, bool) or int(value) < 0 for value in counts):
            raise MonitoringProtocolRuleError(
                "rule coverage counts must be non-negative integers"
            )
        if tuple(sorted(set(self.authoritative_projects))) != tuple(
            self.authoritative_projects
        ):
            raise MonitoringProtocolRuleError(
                "authoritative_projects must be unique and sorted"
            )


@dataclass(frozen=True)
class RuleFamilyCoverageSnapshot:
    rule_family: str
    authoritative_projects: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.rule_family not in ALL_RULE_FAMILIES:
            raise MonitoringProtocolRuleError(
                "rule family coverage uses an unknown rule_family"
            )
        if tuple(sorted(set(self.authoritative_projects))) != tuple(
            self.authoritative_projects
        ):
            raise MonitoringProtocolRuleError(
                "rule family authoritative_projects must be unique and sorted"
            )


def shadow_diagnostic_results_content_sha256(
    results: Sequence[RuleShadowDiagnosticResult],
) -> str:
    return sha256(
        _canonical_json(
            [
                asdict(item)
                for item in sorted(results, key=lambda value: value.case_id)
            ]
        ).encode("utf-8")
    ).hexdigest()


def shadow_coverage_content_sha256(
    rule_coverages: Sequence[RuleRevisionCoverageSnapshot],
    family_coverages: Sequence[RuleFamilyCoverageSnapshot],
) -> str:
    payload = {
        "rules": [
            asdict(item)
            for item in sorted(
                rule_coverages,
                key=lambda value: value.rule_revision_id,
            )
        ],
        "families": [
            asdict(item)
            for item in sorted(
                family_coverages,
                key=lambda value: value.rule_family,
            )
        ],
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuleShadowRun:
    shadow_run_id: str
    project_id: str
    rule_pack_id: str
    batch_id: str
    status: str
    case_count: int
    passed_count: int
    failed_count: int
    results: tuple[RuleShadowCaseResult, ...]
    case_set_content_sha256: str
    completed_at: str
    diagnostic_case_count: int = 0
    diagnostic_passed_count: int = 0
    diagnostic_failed_count: int = 0
    diagnostic_results: tuple[RuleShadowDiagnosticResult, ...] = ()
    diagnostic_case_set_content_sha256: str = ""
    diagnostic_results_content_sha256: str = ""
    rule_coverages: tuple[RuleRevisionCoverageSnapshot, ...] = ()
    family_coverages: tuple[RuleFamilyCoverageSnapshot, ...] = ()
    coverage_content_sha256: str = ""

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_pack_id: str,
        batch_id: str,
        results: Sequence[RuleShadowCaseResult],
        case_set_content_sha256: str,
        completed_at: str,
        diagnostic_results: Sequence[RuleShadowDiagnosticResult] = (),
        diagnostic_case_set_sha256: str = "",
        rule_coverages: Sequence[RuleRevisionCoverageSnapshot] = (),
        family_coverages: Sequence[RuleFamilyCoverageSnapshot] = (),
    ) -> "RuleShadowRun":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_pack_id = _bounded_text(rule_pack_id, "rule_pack_id", 200)
        batch_id = _bounded_text(batch_id, "batch_id", 200)
        completed_at = _bounded_text(completed_at, "completed_at", 80)
        frozen_results = tuple(results)
        frozen_diagnostic_results = tuple(diagnostic_results)
        frozen_rule_coverages = tuple(rule_coverages)
        frozen_family_coverages = tuple(family_coverages)
        if not isinstance(case_set_content_sha256, str) or not re.fullmatch(
            r"^[0-9a-f]{64}$", case_set_content_sha256
        ):
            raise MonitoringProtocolRuleError(
                "shadow run requires a frozen gold case set SHA-256"
            )
        if diagnostic_case_set_sha256 is None or diagnostic_case_set_sha256 == "":
            diagnostic_case_set_content_sha256_value = (
                diagnostic_case_set_content_sha256(())
            )
        elif isinstance(diagnostic_case_set_sha256, str) and re.fullmatch(
            r"^[0-9a-f]{64}$", diagnostic_case_set_sha256
        ):
            diagnostic_case_set_content_sha256_value = diagnostic_case_set_sha256
        else:
            raise MonitoringProtocolRuleError(
                "shadow run requires a frozen diagnostic case set SHA-256"
            )
        passed_count = sum(item.passed for item in frozen_results)
        failed_count = len(frozen_results) - passed_count
        diagnostic_passed_count = sum(
            item.passed for item in frozen_diagnostic_results
        )
        diagnostic_failed_count = (
            len(frozen_diagnostic_results) - diagnostic_passed_count
        )
        diagnostic_results_sha256 = (
            shadow_diagnostic_results_content_sha256(
                frozen_diagnostic_results
            )
        )
        coverage_sha256 = shadow_coverage_content_sha256(
            frozen_rule_coverages,
            frozen_family_coverages,
        )
        status = "completed"
        shadow_run_id = _stable_id(
            "shadowrun",
            project_id,
            rule_pack_id,
            batch_id,
            case_set_content_sha256,
            tuple(asdict(item) for item in frozen_results),
            diagnostic_case_set_content_sha256_value,
            diagnostic_results_sha256,
            coverage_sha256,
        )
        return cls(
            shadow_run_id=shadow_run_id,
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            batch_id=batch_id,
            status=status,
            case_count=len(frozen_results),
            passed_count=passed_count,
            failed_count=failed_count,
            results=frozen_results,
            case_set_content_sha256=case_set_content_sha256,
            diagnostic_case_count=len(frozen_diagnostic_results),
            diagnostic_passed_count=diagnostic_passed_count,
            diagnostic_failed_count=diagnostic_failed_count,
            diagnostic_results=frozen_diagnostic_results,
            diagnostic_case_set_content_sha256=(
                diagnostic_case_set_content_sha256_value
            ),
            diagnostic_results_content_sha256=diagnostic_results_sha256,
            rule_coverages=frozen_rule_coverages,
            family_coverages=frozen_family_coverages,
            coverage_content_sha256=coverage_sha256,
            completed_at=completed_at,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["results"] = [asdict(item) for item in self.results]
        value["diagnostic_results"] = [
            asdict(item) for item in self.diagnostic_results
        ]
        value["rule_coverages"] = [
            asdict(item) for item in self.rule_coverages
        ]
        value["family_coverages"] = [
            asdict(item) for item in self.family_coverages
        ]
        return value


def compare_rule_packs(
    previous_pack: MonitoringRulePack,
    previous_rules: Sequence[MonitoringRuleDefinition],
    current_pack: MonitoringRulePack,
    current_rules: Sequence[MonitoringRuleDefinition],
) -> RulePackImpact:
    if previous_pack.project_id != current_pack.project_id:
        raise MonitoringProtocolRuleError("cannot compare rule packs from different projects")
    previous_by_key = {rule.rule_key: rule for rule in previous_rules}
    current_by_key = {rule.rule_key: rule for rule in current_rules}
    if len(previous_by_key) != len(previous_rules) or len(current_by_key) != len(current_rules):
        raise MonitoringProtocolRuleError("rule pack contains duplicate rule keys")
    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)
    added = current_keys - previous_keys
    superseded = previous_keys - current_keys
    changed = {
        key
        for key in previous_keys & current_keys
        if previous_by_key[key].semantic_fingerprint()
        != current_by_key[key].semantic_fingerprint()
    }
    unchanged = (previous_keys & current_keys) - changed
    return RulePackImpact(
        previous_rule_pack_id=previous_pack.rule_pack_id,
        current_rule_pack_id=current_pack.rule_pack_id,
        added_rule_keys=tuple(sorted(added)),
        changed_rule_keys=tuple(sorted(changed)),
        superseded_rule_keys=tuple(sorted(superseded)),
        unchanged_rule_keys=tuple(sorted(unchanged)),
    )


def build_re_review_tasks(
    impact: RulePackImpact,
    current_rules: Sequence[MonitoringRuleDefinition],
    bindings: Iterable[RuleRiskBinding],
) -> tuple[RuleReReviewTask, ...]:
    current_by_key = {rule.rule_key: rule for rule in current_rules}
    tasks: list[RuleReReviewTask] = []
    impacted = set(impact.changed_rule_keys) | set(impact.superseded_rule_keys)
    for binding in bindings:
        if binding.rule_key not in impacted:
            continue
        current = current_by_key.get(binding.rule_key)
        current_revision = current.rule_revision_id if current is not None else ""
        reason = (
            "规则内容或适用条件已变更，需按新版本重新复核。"
            if current is not None
            else "原规则已从当前规则包移除或被替代，需确认既有风险处置是否仍适用。"
        )
        tasks.append(
            RuleReReviewTask.create(
                binding=binding,
                current_rule_revision_id=current_revision,
                reason=reason,
            )
        )
    return tuple(sorted(tasks, key=lambda item: item.task_id))

SHADOW_PROVISIONAL_SAMPLE_BUCKETS = (
    "positive",
    "negative",
    "boundary",
    "diagnostic",
)
SHADOW_PROVISIONAL_EVALUATION_STATES = ("true", "false", "indeterminate")
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


def _optional_sha256(value: Any, field_name: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or _SHA256_HEX_RE.fullmatch(value) is None:
        raise MonitoringProtocolRuleError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class ShadowProvisionalSample:
    """One immutable server-prepared inspection sample.

    Records only the actual outcome observed during automatic preparation.
    It carries no expected_* fields: it is not gold standard evidence and is
    never trusted for release until a medical confirmation act promotes it.
    """

    sample_id: str
    project_id: str
    rule_key: str
    rule_revision_id: str
    bucket: str
    case_label: str
    business_key: str
    input_record: dict[str, Any]
    related_records: dict[str, list[dict[str, Any]]]
    observed_domains: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    source_row_bindings: tuple[RuleGoldSourceRowBinding, ...]
    actual_matched: bool
    actual_evaluation_state: str
    actual_diagnostic_code: str
    evidence_summary: str

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_key: str,
        rule_revision_id: str,
        bucket: str,
        case_label: str,
        business_key: str,
        input_record: Mapping[str, Any],
        related_records: Mapping[str, Sequence[Mapping[str, Any]]] | None,
        observed_domains: Iterable[str],
        evidence_locators: Iterable[str],
        source_row_bindings: Iterable[
            RuleGoldSourceRowBinding | Mapping[str, Any]
        ],
        actual_matched: bool,
        actual_evaluation_state: str,
        actual_diagnostic_code: str,
        evidence_summary: str,
    ) -> "ShadowProvisionalSample":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_key = _normalize_key(rule_key, "rule_key")
        rule_revision_id = _bounded_text(
            rule_revision_id, "rule_revision_id", 200
        )
        bucket = _validate_enum(
            bucket, "bucket", SHADOW_PROVISIONAL_SAMPLE_BUCKETS
        )
        case_label = _bounded_text(case_label, "case_label", 500)
        business_key = _bounded_text(business_key, "business_key", 500)
        input_value = _validate_mapping(input_record, "input_record")
        related_value = {
            str(domain).strip().upper(): [
                _validate_mapping(item, "related_record") for item in records
            ]
            for domain, records in (related_records or {}).items()
        }
        observed_value = tuple(
            sorted(
                {
                    _bounded_text(item, "observed_domain", 80).upper()
                    for item in observed_domains
                }
            )
        )
        if not observed_value:
            raise MonitoringProtocolRuleError(
                "provisional sample requires observed domains"
            )
        locators = tuple(
            sorted(
                {
                    _bounded_text(item, "evidence_locator", 500)
                    for item in evidence_locators
                }
            )
        )
        if not locators:
            raise MonitoringProtocolRuleError(
                "provisional sample requires evidence locators"
            )
        bindings = tuple(
            sorted(
                (
                    item
                    if isinstance(item, RuleGoldSourceRowBinding)
                    else RuleGoldSourceRowBinding.from_mapping(item)
                    for item in source_row_bindings
                ),
                key=lambda item: (
                    item.source_locator,
                    item.business_key,
                    item.record_roles,
                ),
            )
        )
        binding_locators = [item.source_locator for item in bindings]
        if len(binding_locators) != len(set(binding_locators)):
            raise MonitoringProtocolRuleError(
                "provisional sample source row bindings must be unique by locator"
            )
        if bindings and set(binding_locators) != set(locators):
            raise MonitoringProtocolRuleError(
                "provisional sample source row bindings must cover "
                "evidence locators exactly"
            )
        matched = bool(actual_matched)
        state = str(actual_evaluation_state or "").strip().lower()
        if state not in SHADOW_PROVISIONAL_EVALUATION_STATES:
            raise MonitoringProtocolRuleError(
                "actual_evaluation_state must be one of "
                f"{', '.join(SHADOW_PROVISIONAL_EVALUATION_STATES)}"
            )
        code = str(actual_diagnostic_code or "").strip().lower()
        if bucket == "diagnostic" and not code:
            raise MonitoringProtocolRuleError(
                "diagnostic provisional sample requires actual_diagnostic_code"
            )
        summary = _bounded_text(evidence_summary, "evidence_summary", 4_000)
        sample_id = _stable_id(
            "monshitem",
            project_id,
            rule_key,
            rule_revision_id,
            bucket,
            case_label,
            business_key,
            _canonical_json(input_value),
            _canonical_json(related_value),
            observed_value,
            locators,
            tuple(asdict(item) for item in bindings),
            matched,
            state,
            code,
            summary,
        )
        return cls(
            sample_id=sample_id,
            project_id=project_id,
            rule_key=rule_key,
            rule_revision_id=rule_revision_id,
            bucket=bucket,
            case_label=case_label,
            business_key=business_key,
            input_record=input_value,
            related_records=related_value,
            observed_domains=observed_value,
            evidence_locators=locators,
            source_row_bindings=bindings,
            actual_matched=matched,
            actual_evaluation_state=state,
            actual_diagnostic_code=code,
            evidence_summary=summary,
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observed_domains"] = list(self.observed_domains)
        value["evidence_locators"] = list(self.evidence_locators)
        value["source_row_bindings"] = [
            {
                **asdict(item),
                "record_roles": list(item.record_roles),
            }
            for item in self.source_row_bindings
        ]
        return value


@dataclass(frozen=True)
class ShadowProvisionalSampleSet:
    """Immutable provisional inspection evidence for one frozen batch.

    The set is always provisional: it has no status field that could be
    flipped, and it cannot satisfy gold/diagnostic release gates. Only an
    explicit ShadowSampleMedicalConfirmation may promote its exact frozen
    samples into trusted expectation.

    created_by/created_at are audit metadata excluded from equality so the
    same business act replays deterministically across callers and time.
    """

    sample_set_id: str
    project_id: str
    rule_pack_id: str
    batch_id: str
    batch_version: int
    batch_revision: str
    mapping_revision: str
    mapping_content_sha256: str
    capability_manifest_sha256: str
    effective_capabilities_sha256: str
    rule_revision_ids: tuple[str, ...]
    samples: tuple[ShadowProvisionalSample, ...]
    content_sha256: str
    created_by: str = field(default="", compare=False)
    created_at: str = field(default="", compare=False)

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_pack_id: str,
        batch_id: str,
        batch_version: int,
        batch_revision: str,
        mapping_revision: str,
        mapping_content_sha256: str,
        capability_manifest_sha256: str,
        effective_capabilities_sha256: str,
        rule_revision_ids: Iterable[str],
        samples: Sequence[ShadowProvisionalSample],
        created_by: str,
        created_at: str,
    ) -> "ShadowProvisionalSampleSet":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_pack_id = _bounded_text(rule_pack_id, "rule_pack_id", 200)
        batch_id = _bounded_text(batch_id, "batch_id", 200)
        if isinstance(batch_version, bool) or int(batch_version) < 1:
            raise MonitoringProtocolRuleError(
                "batch_version must be a positive integer"
            )
        batch_version_value = int(batch_version)
        batch_revision = _bounded_text(batch_revision, "batch_revision", 200)
        mapping_revision = _bounded_text(
            mapping_revision, "mapping_revision", 200
        )
        mapping_hash = _optional_sha256(
            mapping_content_sha256, "mapping_content_sha256"
        )
        if not mapping_hash:
            raise MonitoringProtocolRuleError(
                "mapping_content_sha256 is required"
            )
        capability_hash = _optional_sha256(
            capability_manifest_sha256, "capability_manifest_sha256"
        )
        if not capability_hash:
            raise MonitoringProtocolRuleError(
                "capability_manifest_sha256 is required"
            )
        capabilities_hash = _optional_sha256(
            effective_capabilities_sha256, "effective_capabilities_sha256"
        )
        revision_ids = tuple(
            sorted(
                {
                    _bounded_text(item, "rule_revision_id", 200)
                    for item in rule_revision_ids
                }
            )
        )
        if not revision_ids:
            raise MonitoringProtocolRuleError(
                "provisional sample set requires rule revision ids"
            )
        sample_values = tuple(
            sorted(samples, key=lambda item: item.sample_id)
        )
        if not sample_values:
            raise MonitoringProtocolRuleError(
                "provisional sample set requires at least one sample"
            )
        if any(
            not isinstance(item, ShadowProvisionalSample)
            for item in sample_values
        ):
            raise MonitoringProtocolRuleError(
                "provisional sample set samples must be ShadowProvisionalSample"
            )
        if any(item.project_id != project_id for item in sample_values):
            raise MonitoringProtocolRuleError(
                "provisional sample set contains another project's sample"
            )
        if any(
            item.rule_revision_id not in revision_ids
            for item in sample_values
        ):
            raise MonitoringProtocolRuleError(
                "provisional sample set samples must bind the declared "
                "rule revisions"
            )
        content_hash = sha256(
            _canonical_json(
                [item.public_dict() for item in sample_values]
            ).encode("utf-8")
        ).hexdigest()
        sample_set_id = _stable_id(
            "monshsample",
            project_id,
            rule_pack_id,
            batch_id,
            batch_version_value,
            revision_ids,
            mapping_revision,
            mapping_hash,
            capability_hash,
            capabilities_hash,
            content_hash,
        )
        return cls(
            sample_set_id=sample_set_id,
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            batch_id=batch_id,
            batch_version=batch_version_value,
            batch_revision=batch_revision,
            mapping_revision=mapping_revision,
            mapping_content_sha256=mapping_hash,
            capability_manifest_sha256=capability_hash,
            effective_capabilities_sha256=capabilities_hash,
            rule_revision_ids=revision_ids,
            samples=sample_values,
            content_sha256=content_hash,
            created_by=_bounded_text(created_by, "created_by", 160),
            created_at=_bounded_text(created_at, "created_at", 80),
        )

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["rule_revision_ids"] = list(self.rule_revision_ids)
        value["samples"] = [item.public_dict() for item in self.samples]
        return value


@dataclass(frozen=True)
class ShadowSampleMedicalConfirmation:
    """Immutable record of the explicit medical confirmation act.

    The act promotes the exact frozen provisional sample set into trusted
    expectation. confirmed_by/confirmed_at are audit metadata excluded from
    identity: the same business act replays to the same confirmation id.
    """

    confirmation_id: str
    project_id: str
    rule_pack_id: str
    sample_set_id: str
    sample_set_content_sha256: str
    trusted_shadow_run_id: str
    confirmed_by: str = field(default="", compare=False)
    confirmed_at: str = field(default="", compare=False)

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        rule_pack_id: str,
        sample_set_id: str,
        sample_set_content_sha256: str,
        trusted_shadow_run_id: str,
        confirmed_by: str,
        confirmed_at: str,
    ) -> "ShadowSampleMedicalConfirmation":
        project_id = _bounded_text(project_id, "project_id", 160)
        rule_pack_id = _bounded_text(rule_pack_id, "rule_pack_id", 200)
        sample_set_id = _bounded_text(sample_set_id, "sample_set_id", 200)
        content_hash = _optional_sha256(
            sample_set_content_sha256, "sample_set_content_sha256"
        )
        if not content_hash:
            raise MonitoringProtocolRuleError(
                "sample_set_content_sha256 is required"
            )
        trusted_run_id = _bounded_text(
            trusted_shadow_run_id, "trusted_shadow_run_id", 200
        )
        confirmation_id = _stable_id(
            "monshconfirm",
            project_id,
            rule_pack_id,
            sample_set_id,
            content_hash,
        )
        return cls(
            confirmation_id=confirmation_id,
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            sample_set_id=sample_set_id,
            sample_set_content_sha256=content_hash,
            trusted_shadow_run_id=trusted_run_id,
            confirmed_by=_bounded_text(confirmed_by, "confirmed_by", 160),
            confirmed_at=_bounded_text(confirmed_at, "confirmed_at", 80),
        )

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)
