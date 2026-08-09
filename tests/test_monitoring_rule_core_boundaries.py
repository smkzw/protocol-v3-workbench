from __future__ import annotations

from copy import deepcopy

import pytest

from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    ProtocolFact,
)
from services.api.app.monitoring_rule_templates import (
    TEMPLATE_PAYLOAD_KEY,
    TEMPLATE_VERSION,
    MonitoringRuleTemplateError,
    compile_monitoring_rule_template,
)


def _make_core_rule(
    *,
    family: str,
    clinical_domain: str,
    required_domains: tuple[str, ...],
) -> MonitoringRuleDefinition:
    return MonitoringRuleDefinition.create(
        project_id="proj_core_boundary",
        protocol_version_id="protov_core_boundary",
        rule_key=f"test.{family}.core_boundary",
        rule_family=family,
        status="candidate",
        title="核心边界测试规则",
        executor="field_predicate",
        required_domains=required_domains,
        preconditions={"exists": {"field": "SUBJID"}},
        trigger_expression={"eq": {"field": "FLAG", "value": "Y"}},
        exclusions={"missing": {"field": "SUBJID"}},
        severity="high",
        confidence="deterministic",
        evidence_template="{SUBJID}",
        fact_revision_ids=["factrev_core_boundary"],
        source_entry_id="source_core_boundary",
        source_locator="docx:paragraph:1",
        source_text="核心规则边界测试来源。",
        clinical_domain=clinical_domain,
    )


def _raw_lineage(field_name: str) -> dict[str, str]:
    return {
        "source_type": "raw_listing_field",
        "source_locator": (
            f"listing:{'a' * 64}:sheet:LB:header:1:field:{field_name}"
        ),
    }


def _base_lineage(
    *,
    input_field_roles: list[str],
) -> dict[str, object]:
    return {
        "source_type": "auditable_base_value",
        "input_field_roles": input_field_roles,
        "calculation_expression": "raw_numerator / raw_denominator * 100",
        "unit_literal": "percent",
        "source_locator": (
            f"derived-listing:{'a' * 64}:field:AUDITABLE_PERCENT"
        ),
    }


def _lineage_template() -> dict[str, object]:
    return {
        "template_version": TEMPLATE_VERSION,
        "rule_family": "data_quality",
        "rule_key": "test.data_quality.lineage",
        "executor": "field_predicate",
        "required_domains": ["LB"],
        "listing_mapping": {
            "status": "medically_confirmed",
            "fields": {
                "subject_id": {
                    "field": "SUBJID",
                    "domain": "LB",
                    "lineage": _raw_lineage("SUBJID"),
                },
                "raw_numerator": {
                    "field": "LBORRES",
                    "domain": "LB",
                    "lineage": _raw_lineage("LBORRES"),
                },
                "raw_denominator": {
                    "field": "LBORNRHI",
                    "domain": "LB",
                    "lineage": _raw_lineage("LBORNRHI"),
                },
                "auditable_percent": {
                    "field": "AUDITABLE_PERCENT",
                    "domain": "LB",
                    "lineage": _base_lineage(
                        input_field_roles=["raw_numerator", "raw_denominator"]
                    ),
                },
            },
        },
        "preconditions": {"exists": {"field_role": "subject_id"}},
        "trigger_expression": {
            "gt": {"field_role": "auditable_percent", "value": 120}
        },
        "exclusions": {"missing": {"field_role": "subject_id"}},
        "title": "可审计基础值规则",
        "severity": "high",
        "evidence_template": "{subject_id}：基础值超出范围。",
    }


def _lineage_fact(template: dict[str, object]) -> ProtocolFact:
    return ProtocolFact.create(
        project_id="proj_lineage_boundary",
        protocol_version_id="protov_lineage_boundary",
        fact_key="data_quality.lineage.boundary",
        fact_type="data_quality",
        status="medically_confirmed",
        title="字段血缘边界",
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id="source_lineage_boundary",
        source_locator="listing-mapping:lineage-boundary",
        source_text="字段血缘边界测试来源。",
    )


@pytest.mark.parametrize(
    "family",
    ("study_treatment_change", "study_treatment_adherence"),
)
def test_core_rejects_study_treatment_rule_that_manually_includes_cm(
    family: str,
) -> None:
    with pytest.raises(MonitoringProtocolRuleError, match="must not use CM"):
        _make_core_rule(
            family=family,
            clinical_domain="study_treatment",
            required_domains=("EX", "CM"),
        )


def test_core_rejects_cm_policy_rule_that_manually_includes_ex() -> None:
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="must not use EX, EC, DA or IP",
    ):
        _make_core_rule(
            family="concomitant_medication_policy",
            clinical_domain="concomitant_medication",
            required_domains=("CM", "EX"),
        )


def test_cross_domain_consistency_can_bind_cm_and_ip_domains() -> None:
    rule = _make_core_rule(
        family="cross_domain_consistency",
        clinical_domain="protocol_deviation",
        required_domains=("CM", "EX"),
    )
    assert rule.required_domains == ("CM", "EX")


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("missing_lineage", "requires verifiable lineage"),
        ("model_output", "prohibited conclusion lineage source type"),
        ("base_without_inputs", "requires raw input field roles"),
        ("base_input_not_raw", "inputs must be raw listing field roles"),
        ("conclusion_placeholder", "precomputed conclusion placeholder"),
    ),
)
def test_template_lineage_contract_fails_closed(
    mutation: str,
    expected: str,
) -> None:
    template = deepcopy(_lineage_template())
    fields = template["listing_mapping"]["fields"]
    if mutation == "missing_lineage":
        del fields["subject_id"]["lineage"]
    elif mutation == "model_output":
        fields["auditable_percent"]["lineage"] = {
            "source_type": "model_output",
            "source_locator": "model:latest:output:1",
        }
    elif mutation == "base_without_inputs":
        fields["auditable_percent"]["lineage"] = _base_lineage(
            input_field_roles=[]
        )
    elif mutation == "base_input_not_raw":
        fields["raw_numerator"]["lineage"] = {
            "source_type": "auditable_base_value",
            "input_field_roles": ["raw_denominator"],
            "calculation_expression": "raw_denominator",
            "unit_literal": "normalized result",
            "source_locator": (
                f"derived-listing:{'a' * 64}:field:LBORRES"
            ),
        }
    elif mutation == "conclusion_placeholder":
        fields["auditable_percent"] = {
            "field": "PRECOMPUTED_MEDICAL_CONCLUSION",
            "domain": "LB",
            "lineage": _raw_lineage("PRECOMPUTED_MEDICAL_CONCLUSION"),
        }

    with pytest.raises(MonitoringRuleTemplateError, match=expected):
        compile_monitoring_rule_template(_lineage_fact(template))


def test_raw_and_auditable_base_lineage_compiles_as_candidate() -> None:
    fact = _lineage_fact(_lineage_template())
    rule = compile_monitoring_rule_template(fact)

    assert rule.status == "candidate"
    assert rule.field_lineage["raw_numerator"]["lineage"][
        "source_type"
    ] == "raw_listing_field"
    assert rule.field_lineage["auditable_percent"]["lineage"] == {
        "source_type": "auditable_base_value",
        "input_field_roles": ["raw_numerator", "raw_denominator"],
        "calculation_expression": "raw_numerator / raw_denominator * 100",
        "unit_literal": "percent",
        "source_locator": (
            f"derived-listing:{'a' * 64}:field:AUDITABLE_PERCENT"
        ),
    }
    assert fact.normalized_payload[TEMPLATE_PAYLOAD_KEY]["listing_mapping"][
        "fields"
    ] == rule.field_lineage
