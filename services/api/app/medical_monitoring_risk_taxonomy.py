from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Iterable, Mapping


TAXONOMY_VERSION = "medical-monitoring-risk-taxonomy-v1"
_STUDY_TREATMENT_DOMAINS = frozenset({"EX", "EC", "DA", "IP"})
_SOURCE_DOMAIN_ALIASES = {
    "EX2": "EX",
    "EX3": "EX",
}


class MedicalRiskCategoryCode(str, Enum):
    AE_MISSING_REPORT = "ae_missing_report"
    MH_MISSING_REPORT = "mh_missing_report"
    AE_MH_TEMPORAL_OR_CLASSIFICATION_REVIEW = (
        "ae_mh_temporal_or_classification_review"
    )
    CS_NCS_INCONSISTENT = "cs_ncs_inconsistent"
    PROHIBITED_CONCOMITANT_MEDICATION_PD = (
        "prohibited_concomitant_medication_pd"
    )
    RESTRICTED_CONCOMITANT_MEDICATION_PD = (
        "restricted_concomitant_medication_pd"
    )
    STUDY_TREATMENT_DOSE_CHANGE = "study_treatment_dose_change"
    STUDY_TREATMENT_INTERRUPTION = "study_treatment_interruption"
    STUDY_TREATMENT_PERMANENT_DISCONTINUATION = (
        "study_treatment_permanent_discontinuation"
    )
    STUDY_TREATMENT_RESTART = "study_treatment_restart"
    STUDY_TREATMENT_ADHERENCE = "study_treatment_adherence"
    VISIT_WINDOW_OR_ORDER_PD = "visit_window_or_order_pd"
    OTHER_PROTOCOL_EXECUTION_PD = "other_protocol_execution_pd"
    LABORATORY_ABNORMALITY = "laboratory_abnormality"
    CTCAE_GRADE_WORSENING = "ctcae_grade_worsening"
    EFFICACY_ASSESSMENT_MISSING_OR_INCONSISTENT = (
        "efficacy_assessment_missing_or_inconsistent"
    )
    DATA_QUALITY = "data_quality"
    OTHER_MEDICAL_REVIEW = "other_medical_review"


@dataclass(frozen=True)
class MedicalRiskCategoryDefinition:
    code: MedicalRiskCategoryCode
    label: str
    safety_pv_flag: bool
    domain_role: str
    primary_source_domains: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "label": self.label,
            "taxonomy_version": TAXONOMY_VERSION,
            "safety_pv_flag": self.safety_pv_flag,
            "domain_boundary": {
                "role": self.domain_role,
                "primary_source_domains": list(self.primary_source_domains),
            },
        }


@dataclass(frozen=True)
class MedicalRiskCategoryResolution:
    definition: MedicalRiskCategoryDefinition
    source_code: str
    mapping_kind: str

    @property
    def lineage(self) -> dict[str, str] | None:
        if self.mapping_kind == "canonical":
            return None
        return {
            "source_code": self.source_code,
            "mapping_kind": self.mapping_kind,
        }


def _definition(
    code: MedicalRiskCategoryCode,
    label: str,
    *,
    safety_pv_flag: bool = False,
    domain_role: str,
    primary_source_domains: Iterable[str],
) -> MedicalRiskCategoryDefinition:
    return MedicalRiskCategoryDefinition(
        code=code,
        label=label,
        safety_pv_flag=safety_pv_flag,
        domain_role=domain_role,
        primary_source_domains=tuple(primary_source_domains),
    )


_DEFINITIONS = (
    _definition(
        MedicalRiskCategoryCode.AE_MISSING_REPORT,
        "AE漏报",
        safety_pv_flag=True,
        domain_role="adverse_event",
        primary_source_domains=("AE",),
    ),
    _definition(
        MedicalRiskCategoryCode.MH_MISSING_REPORT,
        "MH漏报",
        safety_pv_flag=True,
        domain_role="medical_history",
        primary_source_domains=("MH",),
    ),
    _definition(
        MedicalRiskCategoryCode.AE_MH_TEMPORAL_OR_CLASSIFICATION_REVIEW,
        "AE/MH关系复核",
        safety_pv_flag=True,
        domain_role="ae_mh_review",
        primary_source_domains=("AE", "MH"),
    ),
    _definition(
        MedicalRiskCategoryCode.CS_NCS_INCONSISTENT,
        "CS/NCS判定复核",
        safety_pv_flag=True,
        domain_role="clinical_significance",
        primary_source_domains=("LB", "VS", "EG"),
    ),
    _definition(
        MedicalRiskCategoryCode.PROHIBITED_CONCOMITANT_MEDICATION_PD,
        "禁用合并用药PD",
        domain_role="non_study_concomitant_medication",
        primary_source_domains=("CM",),
    ),
    _definition(
        MedicalRiskCategoryCode.RESTRICTED_CONCOMITANT_MEDICATION_PD,
        "限制合并用药PD",
        domain_role="non_study_concomitant_medication",
        primary_source_domains=("CM",),
    ),
    _definition(
        MedicalRiskCategoryCode.STUDY_TREATMENT_DOSE_CHANGE,
        "试验药物剂量调整",
        domain_role="study_treatment",
        primary_source_domains=("EX", "EC", "DA", "IP"),
    ),
    _definition(
        MedicalRiskCategoryCode.STUDY_TREATMENT_INTERRUPTION,
        "试验药物暂停",
        domain_role="study_treatment",
        primary_source_domains=("EX", "EC", "DA", "IP"),
    ),
    _definition(
        MedicalRiskCategoryCode.STUDY_TREATMENT_PERMANENT_DISCONTINUATION,
        "试验药物永久停药",
        domain_role="study_treatment",
        primary_source_domains=("EX", "EC", "DA", "IP"),
    ),
    _definition(
        MedicalRiskCategoryCode.STUDY_TREATMENT_RESTART,
        "试验药物重启",
        domain_role="study_treatment",
        primary_source_domains=("EX", "EC", "DA", "IP"),
    ),
    _definition(
        MedicalRiskCategoryCode.STUDY_TREATMENT_ADHERENCE,
        "试验药物依从性",
        domain_role="study_treatment",
        primary_source_domains=("EX", "EC", "DA", "IP"),
    ),
    _definition(
        MedicalRiskCategoryCode.VISIT_WINDOW_OR_ORDER_PD,
        "访视窗口/顺序PD",
        domain_role="visit",
        primary_source_domains=("SV", "DV", "DS"),
    ),
    _definition(
        MedicalRiskCategoryCode.OTHER_PROTOCOL_EXECUTION_PD,
        "其他方案执行PD",
        domain_role="protocol_execution",
        primary_source_domains=("SV", "DV", "DS"),
    ),
    _definition(
        MedicalRiskCategoryCode.LABORATORY_ABNORMALITY,
        "实验室异常",
        safety_pv_flag=True,
        domain_role="laboratory",
        primary_source_domains=("LB",),
    ),
    _definition(
        MedicalRiskCategoryCode.CTCAE_GRADE_WORSENING,
        "CTCAE分级升高/异常加重",
        safety_pv_flag=True,
        domain_role="ctcae_longitudinal",
        primary_source_domains=("LB", "VS", "EG"),
    ),
    _definition(
        MedicalRiskCategoryCode.EFFICACY_ASSESSMENT_MISSING_OR_INCONSISTENT,
        "疗效评估缺失/不一致",
        domain_role="efficacy",
        primary_source_domains=("QS", "FA", "RS"),
    ),
    _definition(
        MedicalRiskCategoryCode.DATA_QUALITY,
        "数据质量",
        domain_role="data_quality",
        primary_source_domains=(),
    ),
    _definition(
        MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW,
        "其他医学复核",
        domain_role="cross_domain_or_unspecified",
        primary_source_domains=(),
    ),
)
_BY_CODE = {item.code.value: item for item in _DEFINITIONS}

# Compatibility is intentionally explicit. Coarse historical codes degrade to
# "other" rather than acquiring a more specific medical meaning from free text.
_LEGACY_EXACT = {
    "medication_compliance": MedicalRiskCategoryCode.STUDY_TREATMENT_ADHERENCE,
    "study_drug_adherence_review": MedicalRiskCategoryCode.STUDY_TREATMENT_ADHERENCE,
    "clinically_significant_lab_review": MedicalRiskCategoryCode.LABORATORY_ABNORMALITY,
    "laboratory_abnormality": MedicalRiskCategoryCode.LABORATORY_ABNORMALITY,
    "实验室异常": MedicalRiskCategoryCode.LABORATORY_ABNORMALITY,
}
_LEGACY_COARSE = frozenset(
    {
        "",
        "safety_ae_mh",
        "safety_clinical_data",
        "concomitant_medication",
        "study_treatment",
        "protocol_execution",
        "eligibility",
        "efficacy",
        "efficacy_key_assessment",
        "cross_domain_clue",
        "AE/MH漏报",
    }
)


def risk_taxonomy_payload() -> dict[str, Any]:
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "closed": True,
        "categories": [item.public_dict() for item in _DEFINITIONS],
    }


def canonical_risk_category_codes() -> tuple[str, ...]:
    return tuple(item.code.value for item in _DEFINITIONS)


def resolve_risk_category(code: Any) -> MedicalRiskCategoryResolution:
    source_code = str(code or "").strip()
    if source_code in _BY_CODE:
        return MedicalRiskCategoryResolution(
            definition=_BY_CODE[source_code],
            source_code=source_code,
            mapping_kind="canonical",
        )
    exact = _LEGACY_EXACT.get(source_code)
    if exact is not None:
        return MedicalRiskCategoryResolution(
            definition=_BY_CODE[exact.value],
            source_code=source_code,
            mapping_kind="legacy_exact",
        )
    mapping_kind = "legacy_coarse" if source_code in _LEGACY_COARSE else "unknown"
    return MedicalRiskCategoryResolution(
        definition=_BY_CODE[MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW.value],
        source_code=source_code,
        mapping_kind=mapping_kind,
    )


def project_risk_category(risk: Any) -> dict[str, Any]:
    resolution = resolve_risk_category(getattr(risk, "primary_category", ""))
    tags = set(getattr(risk, "tags", ()) or ())
    payload = {
        "risk_category_code": resolution.definition.code.value,
        "risk_category_label": resolution.definition.label,
        "safety_pv_flag": "safety_pv" in tags,
        "taxonomy_version": TAXONOMY_VERSION,
    }
    if resolution.lineage is not None:
        payload["risk_category_lineage"] = resolution.lineage
    return payload


def normalize_risk_case_category(risk: Any) -> Any:
    resolution = resolve_risk_category(getattr(risk, "primary_category", ""))
    tags = set(getattr(risk, "tags", ()) or ())
    if resolution.lineage is not None:
        tags.add(
            "risk_category_lineage:"
            f"{resolution.mapping_kind}:{resolution.source_code or '<empty>'}"
        )
    return risk.model_copy(
        update={
            "primary_category": resolution.definition.code.value,
            "tags": sorted(tags),
        }
    )


def validate_risk_case_category_domains(risk: Any) -> None:
    resolution = resolve_risk_category(getattr(risk, "primary_category", ""))
    tags = tuple(getattr(risk, "tags", ()) or ())
    domains = {
        _SOURCE_DOMAIN_ALIASES.get(value, value)
        for tag in tags
        if str(tag).startswith("source_domain:")
        if (value := str(tag).partition(":")[2].strip().upper())
    }
    strict_role = resolution.definition.domain_role in {
        "non_study_concomitant_medication",
        "study_treatment",
    }
    if domains or strict_role:
        validate_category_domains(
            resolution.definition.code.value,
            domains,
        )


def classify_rule_risk_category(
    *,
    rule_key: str,
    current_domain: str,
    evaluation: Mapping[str, Any],
) -> MedicalRiskCategoryDefinition:
    domain = str(current_domain or "").strip().upper()
    classification = evaluation.get("classification")
    parameters = classification if isinstance(classification, Mapping) else {}
    explicit_code = str(
        parameters.get("risk_category_code")
        or evaluation.get("risk_category_code")
        or ""
    ).strip()
    if explicit_code:
        if explicit_code not in _BY_CODE:
            raise ValueError(f"unsupported explicit risk category: {explicit_code}")
        definition = _BY_CODE[explicit_code]
    else:
        parameter_code = _category_from_parameters(parameters)
        definition = _BY_CODE[
            parameter_code.value
            if parameter_code is not None
            else _category_from_rule_identity(rule_key).value
        ]
    validate_category_domains(definition.code.value, (domain,))
    return definition


def classify_ai_risk_category(
    *,
    explicit_code: Any,
    evidence_domains: Iterable[str],
) -> MedicalRiskCategoryDefinition:
    code = str(explicit_code or "").strip()
    if not code:
        return _BY_CODE[MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW.value]
    if code not in _BY_CODE:
        raise ValueError(f"unsupported explicit risk category: {code}")
    definition = _BY_CODE[code]
    validate_category_domains(code, evidence_domains)
    return definition


def validate_category_domains(
    code: str,
    source_domains: Iterable[str],
) -> None:
    definition = _BY_CODE.get(code)
    if definition is None:
        raise ValueError(f"unsupported risk category: {code}")
    domains = {
        str(domain or "").strip().upper()
        for domain in source_domains
        if str(domain or "").strip()
    }
    if definition.domain_role == "non_study_concomitant_medication":
        if "CM" not in domains or domains.intersection(_STUDY_TREATMENT_DOMAINS):
            raise ValueError(
                "concomitant-medication categories require CM and prohibit EX/EC/DA/IP"
            )
        return
    if definition.domain_role == "study_treatment":
        if not domains.intersection(_STUDY_TREATMENT_DOMAINS) or "CM" in domains:
            raise ValueError(
                "study-treatment categories require EX/EC/DA/IP and prohibit CM"
            )
        return
    allowed = set(definition.primary_source_domains)
    if allowed and not domains.intersection(allowed):
        raise ValueError(
            f"risk category {code} is incompatible with source domains {sorted(domains)}"
        )


def _category_from_parameters(
    parameters: Mapping[str, Any],
) -> MedicalRiskCategoryCode | None:
    family = str(parameters.get("rule_family") or "").strip()
    subtype = str(
        parameters.get("category_parameter")
        or parameters.get("subtype")
        or ""
    ).strip()
    if not family:
        return None
    keys = (family, subtype)
    return {
        ("ae_mh_missing_review", "ae"): MedicalRiskCategoryCode.AE_MISSING_REPORT,
        ("ae_mh_missing_review", "mh"): MedicalRiskCategoryCode.MH_MISSING_REPORT,
        (
            "ae_mh_missing_review",
            "temporal_or_classification",
        ): MedicalRiskCategoryCode.AE_MH_TEMPORAL_OR_CLASSIFICATION_REVIEW,
        ("cs_ncs_review", ""): MedicalRiskCategoryCode.CS_NCS_INCONSISTENT,
        (
            "concomitant_medication_policy",
            "prohibited",
        ): MedicalRiskCategoryCode.PROHIBITED_CONCOMITANT_MEDICATION_PD,
        (
            "concomitant_medication_policy",
            "restricted",
        ): MedicalRiskCategoryCode.RESTRICTED_CONCOMITANT_MEDICATION_PD,
        (
            "study_treatment_change",
            "dose_change",
        ): MedicalRiskCategoryCode.STUDY_TREATMENT_DOSE_CHANGE,
        (
            "study_treatment_change",
            "interruption",
        ): MedicalRiskCategoryCode.STUDY_TREATMENT_INTERRUPTION,
        (
            "study_treatment_change",
            "permanent_discontinuation",
        ): MedicalRiskCategoryCode.STUDY_TREATMENT_PERMANENT_DISCONTINUATION,
        (
            "study_treatment_change",
            "restart",
        ): MedicalRiskCategoryCode.STUDY_TREATMENT_RESTART,
        (
            "study_treatment_adherence",
            "",
        ): MedicalRiskCategoryCode.STUDY_TREATMENT_ADHERENCE,
        (
            "visit_window_and_order",
            "",
        ): MedicalRiskCategoryCode.VISIT_WINDOW_OR_ORDER_PD,
        (
            "laboratory_abnormality",
            "",
        ): MedicalRiskCategoryCode.LABORATORY_ABNORMALITY,
        (
            "ctcae_longitudinal_worsening",
            "",
        ): MedicalRiskCategoryCode.CTCAE_GRADE_WORSENING,
        (
            "efficacy_endpoint_completeness",
            "",
        ): MedicalRiskCategoryCode.EFFICACY_ASSESSMENT_MISSING_OR_INCONSISTENT,
        ("data_quality", ""): MedicalRiskCategoryCode.DATA_QUALITY,
    }.get(keys)


def _category_from_rule_identity(rule_key: Any) -> MedicalRiskCategoryCode:
    key = re.sub(r"[^a-z0-9]+", ".", str(rule_key or "").strip().lower()).strip(".")
    tokens = tuple(token for token in key.split(".") if token)
    token_set = set(tokens)

    if tokens[:3] in {("ae", "mh", "missing"), ("ae", "missing", "report")}:
        if tokens[-1:] == ("ae",) or "adverse" in token_set:
            return MedicalRiskCategoryCode.AE_MISSING_REPORT
        if tokens[-1:] == ("mh",) or "history" in token_set:
            return MedicalRiskCategoryCode.MH_MISSING_REPORT
    if tokens[:2] == ("ae", "mh") or {"ae", "mh"}.issubset(token_set):
        return MedicalRiskCategoryCode.AE_MH_TEMPORAL_OR_CLASSIFICATION_REVIEW
    if "cs" in token_set and "ncs" in token_set:
        return MedicalRiskCategoryCode.CS_NCS_INCONSISTENT
    if "concomitant" in token_set and "medication" in token_set:
        if "prohibited" in token_set or "washout" in token_set:
            return MedicalRiskCategoryCode.PROHIBITED_CONCOMITANT_MEDICATION_PD
        if "restricted" in token_set:
            return MedicalRiskCategoryCode.RESTRICTED_CONCOMITANT_MEDICATION_PD
        return MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW
    if "study" in token_set and (
        "treatment" in token_set or "drug" in token_set
    ):
        if "adherence" in token_set or "compliance" in token_set:
            return MedicalRiskCategoryCode.STUDY_TREATMENT_ADHERENCE
        if "restart" in token_set or "resume" in token_set:
            return MedicalRiskCategoryCode.STUDY_TREATMENT_RESTART
        if "permanent" in token_set and token_set.intersection(
            {"stop", "discontinue", "discontinuation"}
        ):
            return MedicalRiskCategoryCode.STUDY_TREATMENT_PERMANENT_DISCONTINUATION
        if token_set.intersection({"interrupt", "interruption", "pause", "hold"}):
            return MedicalRiskCategoryCode.STUDY_TREATMENT_INTERRUPTION
        if token_set.intersection({"dose", "increase", "decrease", "reduce"}):
            return MedicalRiskCategoryCode.STUDY_TREATMENT_DOSE_CHANGE
        return MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW
    if "visit" in token_set and token_set.intersection({"window", "order", "schedule"}):
        return MedicalRiskCategoryCode.VISIT_WINDOW_OR_ORDER_PD
    if "laboratory" in token_set or tokens[:1] == ("lab",):
        return MedicalRiskCategoryCode.LABORATORY_ABNORMALITY
    if "ctcae" in token_set:
        return MedicalRiskCategoryCode.CTCAE_GRADE_WORSENING
    if "efficacy" in token_set:
        return MedicalRiskCategoryCode.EFFICACY_ASSESSMENT_MISSING_OR_INCONSISTENT
    if tokens[:2] == ("data", "quality"):
        return MedicalRiskCategoryCode.DATA_QUALITY
    if "protocol" in token_set:
        return MedicalRiskCategoryCode.OTHER_PROTOCOL_EXECUTION_PD
    return MedicalRiskCategoryCode.OTHER_MEDICAL_REVIEW
