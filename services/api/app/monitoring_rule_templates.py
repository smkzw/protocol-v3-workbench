from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Mapping, Optional

from .monitoring_protocol_rules import (
    FACT_TYPE_CLINICAL_DOMAIN,
    RULE_FAMILIES,
    RULE_FAMILY_ALLOWED_DATA_DOMAINS,
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    ProtocolFact,
    validate_rule_field_lineage,
)


TEMPLATE_PAYLOAD_KEY = "deterministic_template"
TEMPLATE_VERSION = "monitoring_rule_template_v2"

_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_CALCULATION_RE = re.compile(r"^[A-Za-z0-9_+\-*/().,\s]+$")
_CALCULATION_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IP_DATA_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_CM_DATA_DOMAIN = "CM"
_RAW_LISTING_FIELD = "raw_listing_field"
_AUDITABLE_BASE_VALUE = "auditable_base_value"
_ALLOWED_LINEAGE_SOURCE_TYPES = frozenset(
    {_RAW_LISTING_FIELD, _AUDITABLE_BASE_VALUE}
)
_DETERMINISTIC_CALCULATION_FUNCTIONS = frozenset(
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
_CONCLUSION_SOURCE_TYPES = frozenset(
    {
        "medical_conclusion",
        "model_output",
        "precomputed_medical_conclusion",
        "review_status",
    }
)
_CONCLUSION_FIELD_MARKERS = (
    "medical_conclusion",
    "model_output",
    "precomputed_medical_conclusion",
    "review_status",
)

_FAMILY_FACT_TYPES = {
    "ae_mh_missing_review": frozenset({"safety_assessment"}),
    "cs_ncs_review": frozenset({"safety_assessment"}),
    "study_treatment_change": frozenset({"study_treatment_change"}),
    "study_treatment_adherence": frozenset({"study_treatment_adherence"}),
    "concomitant_medication_policy": frozenset(
        {
            "concomitant_medication_allowed",
            "concomitant_medication_restricted",
            "concomitant_medication_prohibited",
            "concomitant_medication_rescue",
            "concomitant_medication_washout",
        }
    ),
    "visit_window_and_order": frozenset(
        {"visit_schedule", "visit_window", "early_withdrawal"}
    ),
    "eligibility_continuity": frozenset(
        {"eligibility_inclusion", "eligibility_exclusion"}
    ),
    "ae_sae_aesi_consistency": frozenset(
        {"safety_assessment", "aesi_definition"}
    ),
    "efficacy_endpoint_completeness": frozenset({"efficacy_assessment"}),
    "cross_domain_consistency": frozenset({"protocol_deviation"}),
    "data_quality": frozenset({"data_quality"}),
}


class MonitoringRuleTemplateError(MonitoringProtocolRuleError):
    """A confirmed fact cannot be compiled into a safe deterministic rule."""


@dataclass(frozen=True)
class TemplateCompilationOutcome:
    status: str
    rule_family: str
    rule: Optional[MonitoringRuleDefinition]
    reason: str = ""

    @property
    def requires_manual_review(self) -> bool:
        return self.status == "manual_review"


def template_rule_families() -> tuple[str, ...]:
    """Return the complete project-neutral deterministic template catalogue."""

    return tuple(_FAMILY_FACT_TYPES)


def template_rule_families_for_fact_type(fact_type: str) -> tuple[str, ...]:
    """Return deterministic families that can safely compile the fact type."""

    normalized = str(fact_type or "").strip()
    return tuple(
        family
        for family, fact_types in _FAMILY_FACT_TYPES.items()
        if normalized in fact_types
    )


def compile_monitoring_rule_templates(
    facts: Iterable[ProtocolFact],
) -> tuple[MonitoringRuleDefinition, ...]:
    return tuple(compile_monitoring_rule_template(fact) for fact in facts)


def try_compile_monitoring_rule_template(
    fact: ProtocolFact,
) -> TemplateCompilationOutcome:
    family = _payload_family(fact.normalized_payload)
    try:
        rule = compile_monitoring_rule_template(fact)
    except MonitoringProtocolRuleError as exc:
        return TemplateCompilationOutcome(
            status="manual_review",
            rule_family=family,
            rule=None,
            reason=str(exc),
        )
    return TemplateCompilationOutcome(
        status="compiled",
        rule_family=rule.rule_family,
        rule=rule,
    )


def compile_monitoring_rule_template(
    fact: ProtocolFact,
) -> MonitoringRuleDefinition:
    if fact.status != "medically_confirmed":
        raise MonitoringRuleTemplateError(
            "deterministic templates require a medically_confirmed fact"
        )
    payload = fact.normalized_payload
    template = payload.get(TEMPLATE_PAYLOAD_KEY)
    if not isinstance(template, Mapping):
        raise MonitoringRuleTemplateError(
            f"fact.normalized_payload.{TEMPLATE_PAYLOAD_KEY} is required"
        )
    if template.get("template_version") != TEMPLATE_VERSION:
        raise MonitoringRuleTemplateError(
            f"template_version must be {TEMPLATE_VERSION}"
        )

    family = _required_text(template.get("rule_family"), "rule_family")
    if family not in RULE_FAMILIES:
        raise MonitoringRuleTemplateError(f"unsupported rule family: {family}")
    if fact.fact_type not in _FAMILY_FACT_TYPES[family]:
        raise MonitoringRuleTemplateError(
            f"fact type {fact.fact_type} cannot compile rule family {family}"
        )
    if FACT_TYPE_CLINICAL_DOMAIN[fact.fact_type] != fact.clinical_domain:
        raise MonitoringRuleTemplateError(
            "fact clinical domain is inconsistent with its fact type"
        )

    executor = _required_text(template.get("executor"), "executor")
    if executor not in {"field_predicate", "cross_record", "temporal"}:
        raise MonitoringRuleTemplateError(
            "current deterministic template DSL cannot safely execute this rule; "
            "manual medical review is required"
        )
    required_domains = _normalized_domains(template.get("required_domains"))
    _validate_family_domains(family, required_domains)

    mapping = template.get("listing_mapping")
    if not isinstance(mapping, Mapping):
        raise MonitoringRuleTemplateError("listing_mapping is required")
    if mapping.get("status") != "medically_confirmed":
        raise MonitoringRuleTemplateError(
            "listing_mapping must be medically_confirmed"
        )
    field_roles = _validated_field_roles(
        mapping.get("fields"),
        required_domains=required_domains,
        family=family,
    )

    subtype = str(template.get("template_subtype") or "").strip().lower()
    if subtype == "aesi":
        if fact.fact_type != "aesi_definition" or template.get("aesi_defined") is not True:
            raise MonitoringRuleTemplateError(
                "AESI rules require a medically confirmed aesi_definition fact"
            )

    preconditions = _compile_expression(
        template.get("preconditions"),
        field_roles,
        required_domains,
        path="preconditions",
    )
    trigger = _compile_expression(
        template.get("trigger_expression"),
        field_roles,
        required_domains,
        path="trigger_expression",
    )
    exclusions = _compile_expression(
        template.get("exclusions"),
        field_roles,
        required_domains,
        path="exclusions",
    )
    evidence_template = _compile_evidence_template(
        _required_text(template.get("evidence_template"), "evidence_template"),
        field_roles,
    )
    field_roles = validate_rule_field_lineage(
        field_lineage=field_roles,
        preconditions=preconditions,
        trigger_expression=trigger,
        exclusions=exclusions,
        evidence_template=evidence_template,
        required_domains=required_domains,
    )
    clinical_domain = str(template.get("clinical_domain") or fact.clinical_domain)
    immutable_identity = template.get("immutable_identity")
    identity_kwargs: dict[str, str] = {}
    if immutable_identity is not None:
        if not isinstance(immutable_identity, Mapping):
            raise MonitoringRuleTemplateError(
                "immutable_identity must be an object"
            )
        identity_values = {
            name: str(immutable_identity.get(name) or "").strip()
            for name in (
                "mapping_revision",
                "mapping_content_sha256",
                "capability_manifest_sha256",
                "effective_capabilities_sha256",
                "recommendation_candidate_id",
            )
        }
        missing_identity = [
            name
            for name in (
                "mapping_revision",
                "mapping_content_sha256",
                "capability_manifest_sha256",
                "effective_capabilities_sha256",
            )
            if not identity_values[name]
        ]
        if missing_identity:
            raise MonitoringRuleTemplateError(
                "immutable_identity is incomplete; "
                f"missing {', '.join(missing_identity)}"
            )
        identity_kwargs = identity_values
    title = _required_text(template.get("title"), "title")
    if immutable_identity is None and "医学复核" not in title:
        # Recommendation-chain templates carry a complete immutable identity:
        # adoption is already the medical decision, so no candidate suffix.
        title = f"{title}（需医学复核候选）"
    return MonitoringRuleDefinition.create(
        project_id=fact.project_id,
        protocol_version_id=fact.protocol_version_id,
        rule_key=_required_text(template.get("rule_key"), "rule_key"),
        rule_family=family,
        status="candidate",
        title=title,
        executor=executor,
        required_domains=required_domains,
        preconditions=preconditions,
        trigger_expression=trigger,
        exclusions=exclusions,
        severity=_required_text(template.get("severity"), "severity"),
        confidence="deterministic",
        evidence_template=evidence_template,
        fact_revision_ids=[fact.fact_revision_id],
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
        clinical_domain=clinical_domain,
        field_lineage=field_roles,
        **identity_kwargs,
    )


def _payload_family(payload: Mapping[str, Any]) -> str:
    template = payload.get(TEMPLATE_PAYLOAD_KEY)
    if not isinstance(template, Mapping):
        return ""
    return str(template.get("rule_family") or "").strip()


def _required_text(value: Any, field_name: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise MonitoringRuleTemplateError(f"{field_name} is required")
    return text


def _normalized_domains(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise MonitoringRuleTemplateError("required_domains must be a non-empty list")
    domains = tuple(
        sorted({_required_text(item, "required_domain").upper() for item in value})
    )
    return domains


def _validate_family_domains(family: str, domains: tuple[str, ...]) -> None:
    unexpected = set(domains) - set(RULE_FAMILY_ALLOWED_DATA_DOMAINS[family])
    if unexpected:
        raise MonitoringRuleTemplateError(
            f"rule family {family} has incompatible data domains: {sorted(unexpected)}"
        )
    if family in {"study_treatment_change", "study_treatment_adherence"}:
        if _CM_DATA_DOMAIN in domains or not set(domains).intersection(_IP_DATA_DOMAINS):
            raise MonitoringRuleTemplateError(
                "study treatment rules require an IP domain and must not use CM"
            )
    if family == "concomitant_medication_policy":
        if _CM_DATA_DOMAIN not in domains or set(domains).intersection(_IP_DATA_DOMAINS):
            raise MonitoringRuleTemplateError(
                "concomitant medication rules require CM and must not use IP domains"
            )


def _validated_field_roles(
    value: Any,
    *,
    required_domains: tuple[str, ...],
    family: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or not value:
        raise MonitoringRuleTemplateError("listing_mapping.fields is required")
    output: dict[str, dict[str, Any]] = {}
    for raw_role, raw_binding in value.items():
        role = str(raw_role or "").strip()
        if not _ROLE_RE.fullmatch(role):
            raise MonitoringRuleTemplateError(
                f"invalid project-neutral field role: {role}"
            )
        if not isinstance(raw_binding, Mapping):
            raise MonitoringRuleTemplateError(
                f"field role {role} must declare field and domain"
            )
        if "lineage" not in raw_binding:
            raise MonitoringRuleTemplateError(
                f"field role {role} requires verifiable lineage"
            )
        if set(raw_binding) != {"field", "domain", "lineage"}:
            raise MonitoringRuleTemplateError(
                f"field role {role} must contain field, domain and lineage"
            )
        field_name = _required_text(raw_binding.get("field"), f"{role}.field")
        _reject_conclusion_placeholder(field_name, role=role)
        domain = _required_text(raw_binding.get("domain"), f"{role}.domain").upper()
        if domain not in required_domains:
            raise MonitoringRuleTemplateError(
                f"field role {role} belongs to undeclared data domain {domain}"
            )
        lineage = _validated_lineage_header(raw_binding.get("lineage"), role=role)
        output[role] = {
            "field": field_name,
            "domain": domain,
            "lineage": lineage,
        }
    for role, binding in output.items():
        lineage = binding["lineage"]
        if lineage["source_type"] != _AUDITABLE_BASE_VALUE:
            continue
        input_roles = lineage["input_field_roles"]
        for input_role in input_roles:
            if input_role not in output:
                raise MonitoringRuleTemplateError(
                    f"field role {role} base lineage references unmapped input "
                    f"field role: {input_role}"
                )
            input_lineage = output[input_role]["lineage"]
            if input_lineage["source_type"] != _RAW_LISTING_FIELD:
                raise MonitoringRuleTemplateError(
                    f"field role {role} base lineage inputs must be raw listing "
                    f"field roles: {input_role}"
                )
        unit_field_role = lineage.get("unit_field_role")
        if unit_field_role is not None:
            if unit_field_role not in input_roles:
                raise MonitoringRuleTemplateError(
                    f"field role {role} unit_field_role must reference one of "
                    "its input_field_roles"
                )
            if (
                output[unit_field_role]["lineage"]["source_type"]
                != _RAW_LISTING_FIELD
            ):
                raise MonitoringRuleTemplateError(
                    f"field role {role} unit_field_role must reference a raw "
                    "listing field role"
                )
        _validate_calculation_expression(
            lineage["calculation_expression"],
            input_roles=input_roles,
            role=role,
            unit_field_role=unit_field_role,
        )
    _validate_family_domains(
        family,
        tuple(sorted({binding["domain"] for binding in output.values()})),
    )
    return output


def _validated_lineage_header(value: Any, *, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MonitoringRuleTemplateError(
            f"field role {role} requires verifiable lineage"
        )
    source_type = _required_text(
        value.get("source_type"),
        f"{role}.lineage.source_type",
    ).lower()
    if source_type in _CONCLUSION_SOURCE_TYPES:
        raise MonitoringRuleTemplateError(
            f"field role {role} uses prohibited conclusion lineage source type: "
            f"{source_type}"
        )
    if source_type not in _ALLOWED_LINEAGE_SOURCE_TYPES:
        raise MonitoringRuleTemplateError(
            f"field role {role} lineage source_type must be raw_listing_field "
            "or auditable_base_value"
        )
    source_locator = _validated_lineage_locator(
        value.get("source_locator"),
        role=role,
        source_type=source_type,
    )
    if source_type == _RAW_LISTING_FIELD:
        if set(value) != {"source_type", "source_locator"}:
            raise MonitoringRuleTemplateError(
                f"field role {role} raw lineage must contain only source_type "
                "and source_locator"
            )
        return {
            "source_type": source_type,
            "source_locator": source_locator,
        }

    common = {
        "source_type",
        "input_field_roles",
        "calculation_expression",
        "source_locator",
    }
    unit_keys = {"unit_literal", "unit_field_role"}.intersection(value)
    if len(unit_keys) != 1 or set(value) != common.union(unit_keys):
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage requires input_field_roles, "
            "calculation_expression, source_locator and exactly one of "
            "unit_literal or unit_field_role"
        )
    raw_inputs = value.get("input_field_roles")
    if not isinstance(raw_inputs, (list, tuple)) or not raw_inputs:
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage requires raw input field roles"
        )
    input_roles = tuple(str(item or "").strip() for item in raw_inputs)
    if any(not _ROLE_RE.fullmatch(item) for item in input_roles):
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage has an invalid input field role"
        )
    if len(set(input_roles)) != len(input_roles) or role in input_roles:
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage input roles must be unique and "
            "must not reference itself"
        )
    normalized = {
        "source_type": source_type,
        "input_field_roles": list(input_roles),
        "calculation_expression": _required_text(
            value.get("calculation_expression"),
            f"{role}.lineage.calculation_expression",
        ),
        "source_locator": source_locator,
    }
    unit_key = next(iter(unit_keys))
    normalized[unit_key] = _required_text(
        value.get(unit_key),
        f"{role}.lineage.{unit_key}",
    )
    return normalized


def _validated_lineage_locator(
    value: Any,
    *,
    role: str,
    source_type: str,
) -> str:
    locator = _required_text(value, f"{role}.lineage.source_locator")
    if len(locator) > 1_000:
        raise MonitoringRuleTemplateError(
            f"field role {role} lineage source_locator is too long"
        )
    normalized_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", locator.lower())
        if token
    }
    if "row" in normalized_tokens:
        raise MonitoringRuleTemplateError(
            f"field role {role} lineage source_locator must be stable, not row-scoped"
        )
    if source_type == _RAW_LISTING_FIELD and "header" not in normalized_tokens:
        raise MonitoringRuleTemplateError(
            f"field role {role} raw lineage source_locator must identify a header"
        )
    return locator


def _validate_calculation_expression(
    expression: str,
    *,
    input_roles: tuple[str, ...],
    role: str,
    unit_field_role: Optional[str] = None,
) -> None:
    if not _CALCULATION_RE.fullmatch(expression):
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage calculation_expression is not "
            "deterministic DSL"
        )
    identifiers = set(_CALCULATION_IDENTIFIER_RE.findall(expression))
    unknown = identifiers - set(input_roles) - set(
        _DETERMINISTIC_CALCULATION_FUNCTIONS
    )
    required_calculation_roles = set(input_roles)
    if unit_field_role:
        required_calculation_roles.discard(unit_field_role)
    missing = required_calculation_roles - identifiers
    if unknown or missing:
        raise MonitoringRuleTemplateError(
            f"field role {role} base lineage calculation_expression must use "
            f"only and all input field roles; unknown={sorted(unknown)}, "
            f"missing={sorted(missing)}"
        )


def _reject_conclusion_placeholder(field_name: str, *, role: str) -> None:
    normalized = unicodedata.normalize("NFKC", field_name).strip().lower()
    canonical = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if any(marker in canonical for marker in _CONCLUSION_FIELD_MARKERS):
        raise MonitoringRuleTemplateError(
            f"field role {role} maps a prohibited precomputed conclusion placeholder"
        )


def _compile_expression(
    expression: Any,
    field_roles: Mapping[str, Mapping[str, Any]],
    required_domains: tuple[str, ...],
    *,
    path: str,
) -> dict[str, Any]:
    if not isinstance(expression, Mapping) or len(expression) != 1:
        raise MonitoringRuleTemplateError(
            f"{path} must contain exactly one symbolic predicate operator"
        )
    operator, operand = next(iter(expression.items()))
    if operator in {"all", "any"}:
        if not isinstance(operand, list) or not operand:
            raise MonitoringRuleTemplateError(f"{path}.{operator} must be non-empty")
        return {
            operator: [
                _compile_expression(
                    item,
                    field_roles,
                    required_domains,
                    path=f"{path}.{operator}[{index}]",
                )
                for index, item in enumerate(operand)
            ]
        }
    if operator == "not":
        return {
            "not": _compile_expression(
                operand,
                field_roles,
                required_domains,
                path=f"{path}.not",
            )
        }
    if not isinstance(operand, Mapping):
        raise MonitoringRuleTemplateError(f"{path}.{operator} must be an object")
    if set(operand).intersection(
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
    ):
        raise MonitoringRuleTemplateError(
            f"{path}.{operator} must reference confirmed field roles, not raw fields"
        )

    if operator in {"exists", "missing", "changed"}:
        if set(operand) != {"field_role"}:
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires only field_role"
            )
        return {operator: {"field": _mapped_field(operand["field_role"], field_roles)}}
    if operator == "date_delta_days":
        if set(operand) != {"field_role", "other_field_role", "value"}:
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires field_role, other_field_role and value"
            )
        return {
            operator: {
                "field": _mapped_field(operand["field_role"], field_roles),
                "other_field": _mapped_field(
                    operand["other_field_role"], field_roles
                ),
                "value": operand["value"],
            }
        }
    if operator == "date_compare":
        if set(operand) != {
            "field_role",
            "other_field_role",
            "relation",
        }:
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires field_role, other_field_role and relation"
            )
        return {
            operator: {
                "field": _mapped_field(operand["field_role"], field_roles),
                "other_field": _mapped_field(
                    operand["other_field_role"], field_roles
                ),
                "relation": operand["relation"],
            }
        }
    if operator == "date_delta_range":
        allowed = {
            "field_role",
            "other_field_role",
            "min_days",
            "max_days",
        }
        if not set(operand).issubset(allowed) or not {
            "field_role",
            "other_field_role",
        }.issubset(operand):
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires date field roles and a confirmed range"
            )
        compiled = {
            "field": _mapped_field(operand["field_role"], field_roles),
            "other_field": _mapped_field(
                operand["other_field_role"], field_roles
            ),
        }
        for key in ("min_days", "max_days"):
            if key in operand:
                compiled[key] = operand[key]
        return {operator: compiled}
    if operator == "ratio_range":
        if set(operand) != {
            "numerator_field_role",
            "denominator_field_role",
            "multiplier",
            "min_value",
            "max_value",
        }:
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires numerator/denominator roles, "
                "multiplier and a confirmed range"
            )
        return {
            operator: {
                "numerator_field": _mapped_field(
                    operand["numerator_field_role"], field_roles
                ),
                "denominator_field": _mapped_field(
                    operand["denominator_field_role"], field_roles
                ),
                "multiplier": operand["multiplier"],
                "min_value": operand["min_value"],
                "max_value": operand["max_value"],
            }
        }
    if operator == "no_corresponding_record":
        legacy = ({"domain"}, {"domain", "field_role", "value"})
        structured = {"domain", "match", "date_window"}
        if set(operand) not in legacy and not (
            set(operand).issubset(structured)
            and "domain" in operand
            and ("match" in operand or "date_window" in operand)
        ):
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} requires a declared domain and symbolic "
                "match/date-window conditions"
            )
        domain = _required_text(operand.get("domain"), "domain").upper()
        if domain not in required_domains:
            raise MonitoringRuleTemplateError(
                f"{path}.{operator} targets undeclared domain {domain}"
            )
        compiled: dict[str, Any] = {"domain": domain}
        if "field_role" in operand:
            role = str(operand["field_role"])
            if field_roles.get(role, {}).get("domain") != domain:
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator} field role does not belong to {domain}"
                )
            compiled.update(
                {
                    "field": _mapped_field(role, field_roles),
                    "value": operand["value"],
                }
            )
        if "match" in operand:
            match = operand["match"]
            if not isinstance(match, list) or not match:
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator}.match must be a non-empty list"
                )
            compiled_match: list[dict[str, Any]] = []
            for index, condition in enumerate(match):
                if not isinstance(condition, Mapping):
                    raise MonitoringRuleTemplateError(
                        f"{path}.{operator}.match[{index}] must be an object"
                    )
                if "related_field" in condition or "current_field" in condition:
                    raise MonitoringRuleTemplateError(
                        f"{path}.{operator}.match[{index}] must use field roles"
                    )
                allowed_condition = {
                    "related_field_role",
                    "current_field_role",
                    "value",
                    "operator",
                }
                if not set(condition).issubset(allowed_condition):
                    raise MonitoringRuleTemplateError(
                        f"{path}.{operator}.match[{index}] contains unsupported keys"
                    )
                related_role = str(
                    condition.get("related_field_role", "")
                ).strip()
                if field_roles.get(related_role, {}).get("domain") != domain:
                    raise MonitoringRuleTemplateError(
                        f"{path}.{operator}.match[{index}] related role "
                        f"does not belong to {domain}"
                    )
                item: dict[str, Any] = {
                    "related_field": _mapped_field(related_role, field_roles),
                    "operator": condition.get("operator", "eq"),
                }
                condition_operator = str(item["operator"])
                has_current = "current_field_role" in condition
                has_value = "value" in condition
                if condition_operator in {"exists", "missing"}:
                    if has_current or has_value:
                        raise MonitoringRuleTemplateError(
                            f"{path}.{operator}.match[{index}] {condition_operator} "
                            "does not accept a comparison operand"
                        )
                elif has_current == has_value:
                    raise MonitoringRuleTemplateError(
                        f"{path}.{operator}.match[{index}] requires exactly one "
                        "of current_field_role or value"
                    )
                if has_current:
                    item["current_field"] = _mapped_field(
                        condition["current_field_role"], field_roles
                    )
                elif has_value:
                    item["value"] = condition["value"]
                compiled_match.append(item)
            compiled["match"] = compiled_match
        if "date_window" in operand:
            window = operand["date_window"]
            if not isinstance(window, Mapping):
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator}.date_window must be an object"
                )
            if "related_date_field" in window or "current_date_field" in window:
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator}.date_window must use field roles"
                )
            allowed_window = {
                "related_date_field_role",
                "current_date_field_role",
                "min_days",
                "max_days",
            }
            if not set(window).issubset(allowed_window) or not {
                "related_date_field_role",
                "current_date_field_role",
            }.issubset(window):
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator}.date_window requires date field roles "
                    "and a confirmed range"
                )
            related_role = str(window["related_date_field_role"])
            if field_roles.get(related_role, {}).get("domain") != domain:
                raise MonitoringRuleTemplateError(
                    f"{path}.{operator}.date_window related role "
                    f"does not belong to {domain}"
                )
            compiled_window = {
                "related_date_field": _mapped_field(
                    related_role, field_roles
                ),
                "current_date_field": _mapped_field(
                    window["current_date_field_role"], field_roles
                ),
            }
            for key in ("min_days", "max_days"):
                if key in window:
                    compiled_window[key] = window[key]
            compiled["date_window"] = compiled_window
        return {operator: compiled}
    if operator not in {
        "eq",
        "ne",
        "in",
        "not_in",
        "gt",
        "gte",
        "lt",
        "lte",
        "regex",
    }:
        raise MonitoringRuleTemplateError(
            f"{path} uses a predicate not supported by the deterministic DSL: {operator}"
        )
    if set(operand) != {"field_role", "value"}:
        raise MonitoringRuleTemplateError(
            f"{path}.{operator} requires field_role and value"
        )
    return {
        operator: {
            "field": _mapped_field(operand["field_role"], field_roles),
            "value": operand["value"],
        }
    }


def _mapped_field(
    role: Any,
    field_roles: Mapping[str, Mapping[str, Any]],
) -> str:
    role_name = str(role or "").strip()
    if role_name not in field_roles:
        raise MonitoringRuleTemplateError(
            f"predicate references unmapped field role: {role_name}"
        )
    return field_roles[role_name]["field"]


def _compile_evidence_template(
    template: str,
    field_roles: Mapping[str, Mapping[str, Any]],
) -> str:
    placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template))
    unknown = placeholders - set(field_roles)
    if unknown:
        raise MonitoringRuleTemplateError(
            f"evidence_template references unmapped field roles: {sorted(unknown)}"
        )
    compiled = template
    for role, binding in field_roles.items():
        compiled = compiled.replace("{" + role + "}", "{" + binding["field"] + "}")
    return compiled


if set(_FAMILY_FACT_TYPES) != set(RULE_FAMILIES):
    raise RuntimeError("monitoring rule template catalogue does not cover RULE_FAMILIES")
