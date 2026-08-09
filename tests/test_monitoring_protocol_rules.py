from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    ProtocolApplicabilityConflictError,
    RulePackPublicationError,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    MonitoringRulePack,
    ProtocolFact,
    ProtocolSourceVersion,
    RuleSourceReference,
    RuleDiagnosticCase,
    RuleGoldStandardCase,
    RuleGoldRecordFieldBinding,
    RuleGoldSourceRowBinding,
    RuleRiskBinding,
    RuleShadowCaseResult,
    RuleShadowRun,
    build_re_review_tasks,
    compare_rule_packs,
    normalize_rule_field_lineage_units,
    validate_rule_field_lineage,
    validate_predicate_expression,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
    _predicate_trace_state,
    extract_protocol_amendment_changes,
)
from services.api.app.protocol_text_extractor import parse_protocol_docx


MY008_V3_AMENDMENT = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/3.0/研究方案/"
    "MY008211A-PNH-2-03-V3.0版方案修订说明（2.0到3.0）.docx"
)
MY008_V4_AMENDMENT = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/4.0/"
    "MY008211A-PNH-2-03-V4.0版方案修订说明（3.0到4.0）.docx"
)


def test_predicate_trace_result_requires_literal_boolean_when_state_is_missing() -> None:
    assert (
        _predicate_trace_state(
            {"calculation_status": "calculated", "result": "false"}
        )
        == "false"
    )
    assert (
        _predicate_trace_state(
            {"calculation_status": "calculated", "result": True}
        )
        == "true"
    )


def _version(
    project_id: str,
    label: str,
    version_date: str,
    *,
    effective_from: str = "",
    effective_to: str = "",
    predecessor: str = "",
) -> ProtocolSourceVersion:
    return ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code=f"{project_id}-PROTOCOL",
        version_label=label,
        version_date=version_date,
        source_entry_id=f"source-{project_id}-{label}",
        source_title=f"{project_id} 研究方案 {label}",
        content_sha256=("a" if label == "V1.0" else "b") * 64,
        applicability_status=(
            "project_effective_confirmed" if effective_from else "version_date_only"
        ),
        operational_effective_from=effective_from,
        operational_effective_to=effective_to,
        predecessor_version_id=predecessor,
    )


def test_protocol_source_lineage_hashes_require_exact_lowercase_hex() -> None:
    version_kwargs = {
        "project_id": "proj_source_hash",
        "protocol_code": "PROJ-SOURCE-HASH",
        "version_label": "V1.0",
        "version_date": "2026-01-01",
        "source_entry_id": "source-proj-source-hash-V1.0",
        "source_title": "方案 V1.0",
        "status": "confirmed",
        "applicability_status": "version_date_only",
    }
    for malformed in (f" {'a' * 64}", "A" * 64, 123):
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="content_sha256 must be a SHA-256 digest",
        ):
            ProtocolSourceVersion.create(
                **version_kwargs,
                content_sha256=malformed,
            )

    for malformed in (f" {'b' * 64}", "B" * 64, 123):
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="canonical lowercase SHA-256",
        ):
            RuleSourceReference.create(
                fact_revision_id="fact-source-hash",
                source_entry_id="source-source-hash",
                source_locator="docx:page:1",
                source_text="证据文本",
                source_text_sha256=malformed,
            )


def _fact(
    version: ProtocolSourceVersion,
    *,
    key: str = "study_treatment.regimen.primary",
    fact_type: str = "study_treatment_regimen",
    status: str = "medically_confirmed",
    source_text: str = "受试者每日早晚各服用研究药物一次。",
    ) -> ProtocolFact:
    return ProtocolFact.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_key=key,
        fact_type=fact_type,
        status=status,
        title="研究药物给药方案",
        normalized_payload={"frequency": "BID", "route": "oral"},
        source_entry_id=version.source_entry_id,
        source_locator="docx:table:6:row:10",
        source_text=source_text,
    )


def _rule(
    version: ProtocolSourceVersion,
    fact: ProtocolFact,
    *,
    rule_key: str = "study_treatment.adherence.missed_dose",
    rule_family: str = "study_treatment_adherence",
    trigger_value: str = "漏服",
    status: str = "enabled",
    mapping_revision: str = "mapping-v1",
    mapping_content_sha256: str = "2" * 64,
    capability_manifest_sha256: str = "5" * 64,
    effective_capabilities_sha256: str = "6" * 64,
) -> MonitoringRuleDefinition:
    required_domain = (
        "CM" if rule_family == "concomitant_medication_policy" else "EX"
    )
    listing_sha256 = sha256(
        f"{version.project_id}:synthetic-listing".encode("utf-8")
    ).hexdigest()
    field_lineage = {
        role: {
            "field": field_name,
            "domain": required_domain,
            "lineage": {
                "source_type": "raw_listing_field",
                "source_locator": (
                    f"listing:{listing_sha256}:sheet:{required_domain}:"
                    f"header:1:field:{field_name}"
                ),
            },
        }
        for role, field_name in (
            ("subject_id", "SUBJID"),
            ("treatment_description", "EXDESC"),
            ("event_date", "date"),
            ("visit_name", "visit"),
        )
    }
    return MonitoringRuleDefinition.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rule_key=rule_key,
        rule_family=rule_family,
        status=status,
        title="研究药物依从性记录需复核",
        executor="field_predicate",
        required_domains=[required_domain],
        preconditions={"exists": {"field": "SUBJID"}},
        trigger_expression={"regex": {"field": "EXDESC", "value": trigger_value}},
        exclusions={"missing": {"field": "EXDESC"}},
        severity="high",
        confidence="deterministic",
        evidence_template="{date} {visit} 研究药物记录：{EXDESC}",
        fact_revision_ids=[fact.fact_revision_id],
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
        field_lineage=field_lineage,
        mapping_revision=mapping_revision,
        mapping_content_sha256=mapping_content_sha256,
        capability_manifest_sha256=capability_manifest_sha256,
        effective_capabilities_sha256=effective_capabilities_sha256,
    )


def _gold_case_source(
    rule: MonitoringRuleDefinition,
    label: str,
) -> tuple[str, dict[str, Any]]:
    content_sha256 = sha256(
        f"{rule.project_id}:{rule.rule_revision_id}:{label}".encode("utf-8")
    ).hexdigest()
    locator = (
        f"listing:{content_sha256}:sheet:{rule.required_domains[0]}:row:2"
    )
    return locator, {
        "rule_revision_id": rule.rule_revision_id,
        "source_entry_id": f"source-{content_sha256[:16]}",
        "source_content_sha256": content_sha256,
        "source_revision": "source-revision-1",
        "batch_revision": "batch-revision-1",
        "source_row_bindings": (
            RuleGoldSourceRowBinding.create(
                business_key=f"synthetic:{rule.required_domains[0]}:2",
                domain=rule.required_domains[0],
                source_locator=locator,
                row_fingerprint=sha256(
                    f"{content_sha256}:{locator}".encode("utf-8")
                ).hexdigest(),
                record_roles=("current",),
                field_bindings=(
                    RuleGoldRecordFieldBinding.create(
                        record_role="current",
                        record_field="SUBJID",
                        source_field="SUBJID",
                    ),
                ),
            ),
        ),
    }


def _pack(
    repository: MonitoringProtocolRuleRepository,
    version: ProtocolSourceVersion,
    rules: list[MonitoringRuleDefinition],
    *,
    status: str = "published",
) -> MonitoringRulePack:
    return MonitoringRulePack.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        pack_revision=repository.next_pack_revision(version.project_id),
        status=status,
        applicability_status=version.applicability_status,
        rules=rules,
        created_by="medical_manager",
        published_at="2026-07-29T00:00:00+00:00" if status == "published" else "",
    )


def _start_shadow_pack(
    repository: MonitoringProtocolRuleRepository,
    version: ProtocolSourceVersion,
    rules: list[MonitoringRuleDefinition],
    *,
    clock: str = "2026-01-15T00:00:00+00:00",
) -> tuple[
    MonitoringRuleLifecycleService,
    MonitoringRulePack,
    list[MonitoringRuleDefinition],
]:
    lifecycle = MonitoringRuleLifecycleService(
        repository,
        clock=lambda: clock,
    )
    candidate_rules = [
        replace(rule, status="candidate", state_version=1) for rule in rules
    ]
    draft = lifecycle.create_draft_from_confirmed_facts(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rules=candidate_rules,
        created_by="rule_author",
    )
    confirmed_rules = [
        lifecycle.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=rule.state_version,
            confirmed_by="medical_manager",
        )
        for rule in candidate_rules
    ]
    shadow = lifecycle.start_shadow(
        draft.rule_pack_id,
        started_by="shadow_operator",
    )
    return lifecycle, shadow, confirmed_rules


def _publish_pack(
    repository: MonitoringProtocolRuleRepository,
    version: ProtocolSourceVersion,
    rules: list[MonitoringRuleDefinition],
    *,
    clock: str = "2026-01-15T00:00:00+00:00",
) -> MonitoringRulePack:
    if repository._gold_case_authority is None:
        repository.bind_gold_case_authority(lambda _case, _rule: None)
    lifecycle, shadow, confirmed_rules = _start_shadow_pack(
        repository,
        version,
        rules,
        clock=clock,
    )
    _store_p7c_release_evidence(repository, confirmed_rules)
    run = MonitoringProtocolRuleService(repository).run_shadow_validation(
        rule_pack_id=shadow.rule_pack_id,
        batch_id=f"release-{shadow.rule_pack_id}",
    )
    confirmed = lifecycle.confirm_shadow(
        shadow.rule_pack_id,
        shadow_run_id=run.shadow_run_id,
        confirmed_by="medical_manager",
    )
    return lifecycle.publish(
        confirmed.rule_pack_id,
        published_by="medical_manager",
    )


def _store_p7c_release_evidence(
    repository: MonitoringProtocolRuleRepository,
    confirmed_rules: list[MonitoringRuleDefinition],
    *,
    secondary_coverage: str = "complete",
) -> None:
    if secondary_coverage not in {"complete", "negative_only"}:
        raise ValueError("unsupported secondary_coverage")
    cases: list[RuleGoldStandardCase] = []
    diagnostic_cases: list[RuleDiagnosticCase] = []
    for rule in confirmed_rules:
        trigger = rule.trigger_expression.get("regex")
        if trigger is None:
            trigger = rule.trigger_expression.get("eq", {})
        trigger_field = str(trigger.get("field", "EXDESC"))
        trigger_value = str(trigger.get("value", "P7C_POSITIVE")).split("|", 1)[0]
        positive_locator, positive_source = _gold_case_source(
            rule,
            f"release-positive-{rule.rule_revision_id}",
        )
        cases.append(
            RuleGoldStandardCase.create(
                **positive_source,
                project_id=rule.project_id,
                rule_key=rule.rule_key,
                case_label=f"release-positive-{rule.rule_revision_id}",
                input_record={
                    "SUBJID": "RELEASE-POSITIVE",
                    trigger_field: trigger_value,
                    "evidence_span_ids": [positive_locator],
                },
                observed_domains=rule.required_domains,
                expected_match=True,
                coverage_labels=("positive",),
                medical_rationale="确定性阳性发布夹具。",
                evidence_locators=[positive_locator],
            )
        )
        negative_locator, negative_source = _gold_case_source(
            rule,
            f"release-boundary-{rule.rule_revision_id}",
        )
        cases.append(
            RuleGoldStandardCase.create(
                **negative_source,
                project_id=rule.project_id,
                rule_key=rule.rule_key,
                case_label=f"release-boundary-{rule.rule_revision_id}",
                input_record={
                    "SUBJID": "RELEASE-BOUNDARY",
                    trigger_field: "__P7C_NO_MATCH__",
                    "evidence_span_ids": [negative_locator],
                },
                observed_domains=rule.required_domains,
                expected_match=False,
                coverage_labels=("negative", "boundary"),
                medical_rationale="确定性阴性边界发布夹具。",
                evidence_locators=[negative_locator],
            )
        )
        diagnostic_locator, diagnostic_source = _gold_case_source(
            rule,
            f"release-diagnostic-{rule.rule_revision_id}",
        )
        diagnostic_cases.append(
            RuleDiagnosticCase.create(
                **diagnostic_source,
                project_id=rule.project_id,
                rule_key=rule.rule_key,
                case_label=f"release-diagnostic-{rule.rule_revision_id}",
                input_record={
                    "SUBJID": "RELEASE-DIAGNOSTIC",
                    "evidence_span_ids": [diagnostic_locator],
                },
                observed_domains=("ZZ",),
                expected_diagnostic_category="missing_input",
                expected_diagnostic_code="missing_required_domains",
                medical_rationale="缺失规则所需域时必须不可判定。",
                evidence_locators=[diagnostic_locator],
            )
        )
    repository.store_gold_cases(cases)
    repository.store_diagnostic_cases(diagnostic_cases)
    for family in {
        rule.rule_family
        for rule in confirmed_rules
        if rule.rule_family
        in {
            "ae_mh_missing_review",
            "cs_ncs_review",
            "concomitant_medication_policy",
            "study_treatment_change",
            "study_treatment_adherence",
            "visit_window_and_order",
            "laboratory_abnormality",
            "ctcae_longitudinal_worsening",
        }
    }:
        secondary_project = f"fixture-secondary-{family}"

        secondary_version = repository.register_protocol_version(
            _version(
                secondary_project,
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-01",
            )
        )
        secondary_fact_type = {
            "ae_mh_missing_review": "safety_assessment",
            "cs_ncs_review": "safety_assessment",
            "concomitant_medication_policy": (
                "concomitant_medication_prohibited"
            ),
            "study_treatment_change": "study_treatment_change",
            "study_treatment_adherence": "study_treatment_adherence",
            "visit_window_and_order": "visit_window",
            "laboratory_abnormality": "safety_assessment",
            "ctcae_longitudinal_worsening": "safety_assessment",
        }[family]
        secondary_fact = repository.store_fact(
            _fact(
                secondary_version,
                key=f"p7c.secondary.{family}",
                fact_type=secondary_fact_type,
            )
        )
        source_rule = next(
            rule for rule in confirmed_rules if rule.rule_family == family
        )
        secondary_rule = MonitoringRuleDefinition.create(
            project_id=secondary_project,
            protocol_version_id=secondary_version.protocol_version_id,
            rule_key=source_rule.rule_key,
            rule_family=source_rule.rule_family,
            status="candidate",
            title=source_rule.title,
            executor=source_rule.executor,
            required_domains=source_rule.required_domains,
            preconditions=source_rule.preconditions,
            trigger_expression=source_rule.trigger_expression,
            exclusions=source_rule.exclusions,
            severity=source_rule.severity,
            confidence=source_rule.confidence,
            evidence_template=source_rule.evidence_template,
            fact_revision_ids=(secondary_fact.fact_revision_id,),
            source_entry_id=secondary_fact.source_entry_id,
            source_locator=secondary_fact.source_locator,
            source_text=secondary_fact.source_text,
            clinical_domain=source_rule.clinical_domain,
            field_lineage=source_rule.field_lineage,
        )
        secondary_lifecycle = MonitoringRuleLifecycleService(repository)
        secondary_lifecycle.create_draft(
            project_id=secondary_project,
            protocol_version_id=secondary_version.protocol_version_id,
            rules=[secondary_rule],
            created_by="fixture",
        )
        secondary_negative_locator, secondary_negative_source = _gold_case_source(
            secondary_rule,
            f"secondary-negative-{family}",
        )
        repository.store_gold_cases(
            (
                RuleGoldStandardCase.create(
                    **secondary_negative_source,
                    project_id=secondary_project,
                    rule_key=secondary_rule.rule_key,
                    case_label=f"secondary-negative-{family}",
                    input_record={
                        "SUBJID": "SECONDARY",
                        "EXDESC": "按计划完成服药",
                        "evidence_span_ids": [secondary_negative_locator],
                    },
                    observed_domains=secondary_rule.required_domains,
                    expected_match=False,
                    coverage_labels=("negative",),
                    medical_rationale="第二项目权威来源夹具。",
                    evidence_locators=[secondary_negative_locator],
                ),
            )
        )
        if secondary_coverage == "negative_only":
            continue
        secondary_trigger = secondary_rule.trigger_expression.get("regex")
        if secondary_trigger is None:
            secondary_trigger = secondary_rule.trigger_expression.get(
                "eq",
                {},
            )
        secondary_trigger_field = str(
            secondary_trigger.get("field", "EXDESC")
        )
        secondary_trigger_value = str(
            secondary_trigger.get("value", "P7C_POSITIVE")
        ).split("|", 1)[0]
        secondary_positive_locator, secondary_positive_source = (
            _gold_case_source(
                secondary_rule,
                f"secondary-positive-{family}",
            )
        )
        secondary_boundary_locator, secondary_boundary_source = (
            _gold_case_source(
                secondary_rule,
                f"secondary-boundary-{family}",
            )
        )
        repository.store_gold_cases(
            (
                RuleGoldStandardCase.create(
                    **secondary_positive_source,
                    project_id=secondary_project,
                    rule_key=secondary_rule.rule_key,
                    case_label=f"secondary-positive-{family}",
                    input_record={
                        "SUBJID": "SECONDARY-POSITIVE",
                        secondary_trigger_field: secondary_trigger_value,
                        "evidence_span_ids": [secondary_positive_locator],
                    },
                    observed_domains=secondary_rule.required_domains,
                    expected_match=True,
                    coverage_labels=("positive",),
                    medical_rationale="第二项目阳性权威来源夹具。",
                    evidence_locators=[secondary_positive_locator],
                ),
                RuleGoldStandardCase.create(
                    **secondary_boundary_source,
                    project_id=secondary_project,
                    rule_key=secondary_rule.rule_key,
                    case_label=f"secondary-boundary-{family}",
                    input_record={
                        "SUBJID": "SECONDARY-BOUNDARY",
                        secondary_trigger_field: "__P7C_NO_MATCH__",
                        "evidence_span_ids": [secondary_boundary_locator],
                    },
                    observed_domains=secondary_rule.required_domains,
                    expected_match=False,
                    coverage_labels=("negative", "boundary"),
                    medical_rationale="第二项目边界权威来源夹具。",
                    evidence_locators=[secondary_boundary_locator],
                ),
            )
        )
        secondary_diagnostic_locator, secondary_diagnostic_source = (
            _gold_case_source(
                secondary_rule,
                f"secondary-diagnostic-{family}",
            )
        )
        repository.store_diagnostic_cases(
            (
                RuleDiagnosticCase.create(
                    **secondary_diagnostic_source,
                    project_id=secondary_project,
                    rule_key=secondary_rule.rule_key,
                    case_label=f"secondary-diagnostic-{family}",
                    input_record={
                        "SUBJID": "SECONDARY-DIAGNOSTIC",
                        "evidence_span_ids": [
                            secondary_diagnostic_locator
                        ],
                    },
                    observed_domains=("ZZ",),
                    expected_diagnostic_category="missing_input",
                    expected_diagnostic_code="missing_required_domains",
                    medical_rationale="第二项目不可判定权威来源夹具。",
                    evidence_locators=[secondary_diagnostic_locator],
                ),
            )
        )


def test_gold_and_diagnostic_case_source_hashes_require_exact_lowercase_hex() -> None:
    version = _version("proj_case_hash", "V1.0", "2026-01-01")
    fact = _fact(version)
    rule = _rule(version, fact, status="candidate")
    locator, source = _gold_case_source(rule, "case-hash-shape")
    for malformed in (f" {'a' * 64}", "A" * 64, 123):
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="source_content_sha256 must be a lowercase SHA-256 digest",
        ):
            RuleGoldStandardCase.create(
                **{**source, "source_content_sha256": malformed},
                project_id=rule.project_id,
                rule_key=rule.rule_key,
                case_label="case-hash-shape",
                input_record={"SUBJID": "S001", "evidence_span_ids": [locator]},
                observed_domains=rule.required_domains,
                expected_match=True,
                coverage_labels=("positive",),
                medical_rationale="摘要形状回归。",
                evidence_locators=[locator],
            )
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="source_content_sha256 must be a lowercase SHA-256 digest",
        ):
            RuleDiagnosticCase.create(
                **{**source, "source_content_sha256": malformed},
                project_id=rule.project_id,
                rule_key=rule.rule_key,
                case_label="case-hash-shape",
                input_record={"SUBJID": "S001", "evidence_span_ids": [locator]},
                observed_domains=rule.required_domains,
                expected_diagnostic_category="missing_input",
                expected_diagnostic_code="missing_required_domains",
                medical_rationale="摘要形状回归。",
                evidence_locators=[locator],
            )


def test_gold_and_diagnostic_case_locators_require_exact_source_hash_bytes() -> None:
    version = _version("proj_case_locator_hash", "V1.0", "2026-01-01")
    fact = _fact(version)
    rule = _rule(version, fact, status="candidate")
    locator, source = _gold_case_source(rule, "locator-hash-shape")
    source_hash = source["source_content_sha256"]
    upper_locator = locator.replace(source_hash, source_hash.upper())
    source_without_bindings = {
        **source,
        "source_row_bindings": (),
    }

    with pytest.raises(
        MonitoringProtocolRuleError,
        match="gold standard case evidence locators must bind source_content_sha256",
    ):
        RuleGoldStandardCase.create(
            **source_without_bindings,
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            case_label="locator-hash-shape",
            input_record={"SUBJID": "S001", "evidence_span_ids": [upper_locator]},
            observed_domains=rule.required_domains,
            expected_match=True,
            coverage_labels=("positive",),
            medical_rationale="定位器摘要字节回归。",
            evidence_locators=[upper_locator],
        )

    with pytest.raises(
        MonitoringProtocolRuleError,
        match="diagnostic case evidence locators must bind source_content_sha256",
    ):
        RuleDiagnosticCase.create(
            **source_without_bindings,
            project_id=rule.project_id,
            rule_key=rule.rule_key,
            case_label="locator-hash-shape",
            input_record={"SUBJID": "S001", "evidence_span_ids": [upper_locator]},
            observed_domains=rule.required_domains,
            expected_diagnostic_category="missing_input",
            expected_diagnostic_code="missing_required_domains",
            medical_rationale="定位器摘要字节回归。",
            evidence_locators=[upper_locator],
        )


def test_gold_source_row_fingerprints_require_exact_lowercase_hex() -> None:
    version = _version("proj_row_fingerprint", "V1.0", "2026-01-01")
    fact = _fact(version)
    rule = _rule(version, fact, status="candidate")
    locator, source = _gold_case_source(rule, "row-fingerprint-shape")
    binding = source["source_row_bindings"][0]
    for malformed in (f" {binding.row_fingerprint}", binding.row_fingerprint.upper(), 123):
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="gold source row binding requires a lowercase SHA-256 row fingerprint",
        ):
            RuleGoldSourceRowBinding.create(
                business_key=binding.business_key,
                domain=binding.domain,
                source_locator=binding.source_locator,
                row_fingerprint=malformed,
                record_roles=binding.record_roles,
                field_bindings=binding.field_bindings,
            )

        with pytest.raises(
            MonitoringProtocolRuleError,
            match="legacy gold source row binding has an invalid row fingerprint",
        ):
            RuleGoldSourceRowBinding.from_mapping(
                {
                    "business_key": binding.business_key,
                    "domain": binding.domain,
                    "source_locator": locator,
                    "row_fingerprint": malformed,
                    "record_roles": binding.record_roles,
                    "field_bindings": (),
                }
            )


def test_shadow_run_case_set_hashes_require_exact_lowercase_hex() -> None:
    result = RuleShadowCaseResult(
        case_id="gold-case-001",
        rule_key="study_treatment.adherence.missed_dose",
        rule_revision_id="monrule_shadow_hash",
        expected_match=False,
        actual_match=False,
        passed=True,
        evidence_summary="影子运行摘要形状回归。",
    )
    valid_gold_hash = "a" * 64
    for malformed in (f" {valid_gold_hash}", valid_gold_hash.upper(), 123):
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="shadow run requires a frozen gold case set SHA-256",
        ):
            RuleShadowRun.create(
                project_id="proj_shadow_hash",
                rule_pack_id="pack_shadow_hash",
                batch_id="shadow-hash-shape",
                results=[result],
                case_set_content_sha256=malformed,
                completed_at="2026-01-15T00:00:00+00:00",
            )
        with pytest.raises(
            MonitoringProtocolRuleError,
            match="shadow run requires a frozen diagnostic case set SHA-256",
        ):
            RuleShadowRun.create(
                project_id="proj_shadow_hash",
                rule_pack_id="pack_shadow_hash",
                batch_id="shadow-hash-shape",
                results=[result],
                case_set_content_sha256=valid_gold_hash,
                diagnostic_case_set_sha256=malformed,
                completed_at="2026-01-15T00:00:00+00:00",
            )


def test_rule_contract_rejects_embedded_project_code_and_requires_openable_source() -> None:
    version = _version("proj_alpha", "V1.0", "2026-01-01")
    fact = _fact(version)

    with pytest.raises(MonitoringProtocolRuleError, match="unsupported operator"):
        MonitoringRuleDefinition.create(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rule_key="study_treatment.adherence.missed_dose",
            rule_family="study_treatment_adherence",
            status="enabled",
            title="研究药物依从性",
            executor="field_predicate",
            required_domains=["EX"],
            preconditions={"exists": {"field": "SUBJID"}},
            trigger_expression={"python_code": {"value": "if project == 'alpha'"}},
            exclusions={"missing": {"field": "EXDESC"}},
            severity="high",
            confidence="deterministic",
            evidence_template="{EXDESC}",
            fact_revision_ids=[fact.fact_revision_id],
            source_entry_id=fact.source_entry_id,
            source_locator=fact.source_locator,
            source_text=fact.source_text,
        )

    rule = _rule(version, fact)
    source = rule.public_dict()
    assert source["source_text"] == fact.source_text
    assert source["source_locator"] == fact.source_locator
    assert "source_text_sha256" not in source


def test_cm_and_study_treatment_are_separate_fact_and_rule_domains() -> None:
    version = _version("proj_alpha", "V1.0", "2026-01-01")
    ip_fact = _fact(version)
    cm_fact = _fact(
        version,
        key="concomitant_medication.prohibited.complement_inhibitor",
        fact_type="concomitant_medication_prohibited",
        source_text="研究期间禁止使用其他补体抑制剂。",
    )
    ip_rule = _rule(version, ip_fact)
    cm_rule = _rule(
        version,
        cm_fact,
        rule_key="concomitant_medication.prohibited.complement_inhibitor",
        rule_family="concomitant_medication_policy",
        trigger_value="补体抑制剂",
    )

    assert ip_fact.fact_type == "study_treatment_regimen"
    assert cm_fact.fact_type == "concomitant_medication_prohibited"
    assert ip_rule.rule_family == "study_treatment_adherence"
    assert cm_rule.rule_family == "concomitant_medication_policy"
    assert ip_rule.rule_key != cm_rule.rule_key


def test_published_pack_requires_medically_confirmed_facts() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        candidate = repository.store_fact(_fact(version, status="ai_candidate"))
        rule = _rule(version, candidate, status="candidate")
        lifecycle = MonitoringRuleLifecycleService(repository)

        with pytest.raises(RulePackPublicationError, match="medically confirmed"):
            lifecycle.create_draft_from_confirmed_facts(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                rules=[rule],
                created_by="rule_author",
            )


def test_confirmed_protocol_effective_intervals_cannot_overlap() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        first = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
                effective_to="2026-03-31",
            )
        )
        with pytest.raises(ProtocolApplicabilityConflictError, match="overlap"):
            repository.register_protocol_version(
                _version(
                    "proj_alpha",
                    "V2.0",
                    "2026-03-01",
                    effective_from="2026-03-15",
                    predecessor=first.protocol_version_id,
                )
            )


def test_current_pack_fails_closed_without_operational_effective_date() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        version = repository.register_protocol_version(
            _version("proj_alpha", "V1.0", "2026-01-01")
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        with pytest.raises(
            RulePackPublicationError,
            match="operational applicability",
        ):
            _publish_pack(repository, version, [rule])


def test_rule_pack_diff_reopens_only_changed_or_removed_rule_bindings() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        v1 = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-01",
                effective_to="2026-03-31",
            )
        )
        f1 = repository.store_fact(_fact(v1))
        unchanged_v1 = _rule(v1, f1)
        changed_v1 = _rule(
            v1,
            f1,
            rule_key="study_treatment.change.restart",
            rule_family="study_treatment_change",
            trigger_value="恢复",
        )
        removed_v1 = _rule(
            v1,
            f1,
            rule_key="study_treatment.change.fixed_visit",
            rule_family="study_treatment_change",
            trigger_value="V9",
        )
        p1 = _pack(
            repository,
            v1,
            [unchanged_v1, changed_v1, removed_v1],
            status="draft",
        )

        v2 = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V2.0",
                "2026-04-01",
                effective_from="2026-04-01",
                predecessor=v1.protocol_version_id,
            )
        )
        f2 = repository.store_fact(_fact(v2))
        unchanged_v2 = _rule(v2, f2)
        changed_v2 = _rule(
            v2,
            f2,
            rule_key="study_treatment.change.restart",
            rule_family="study_treatment_change",
            trigger_value="恢复|重启",
        )
        p2 = _pack(
            repository,
            v2,
            [unchanged_v2, changed_v2],
            status="draft",
        )

        impact = compare_rule_packs(
            p1,
            [unchanged_v1, changed_v1, removed_v1],
            p2,
            [unchanged_v2, changed_v2],
        )
        assert impact.changed_rule_keys == ("study_treatment.change.restart",)
        assert impact.superseded_rule_keys == (
            "study_treatment.change.fixed_visit",
        )

        bindings = [
            RuleRiskBinding("risk-changed", "proj_alpha", changed_v1.rule_key, changed_v1.rule_revision_id),
            RuleRiskBinding("risk-removed", "proj_alpha", removed_v1.rule_key, removed_v1.rule_revision_id),
        ]
        tasks = build_re_review_tasks(
            impact,
            [unchanged_v2, changed_v2],
            bindings,
        )
        assert {task.risk_instance_id for task in tasks} == {
            "risk-changed",
            "risk-removed",
        }
        assert repository.store_re_review_tasks(tasks) == tasks
        assert repository.store_re_review_tasks(tasks) == tasks
        assert repository.integrity_check() == "ok"


@pytest.mark.parametrize(
    ("project_id", "source_text"),
    (
        ("proj_rux_ad", "试验药物漏用、暂停、恢复或减量均需核对原始记录。"),
        ("proj_my009_uc", "试验药物未服用、多服或非计划服用需核对依从性。"),
        ("proj_my008_pnh", "试验药物剂量递减、换药和撤药随访需独立记录。"),
    ),
)
def test_same_project_neutral_contract_adapts_three_real_study_shapes(
    project_id: str,
    source_text: str,
) -> None:
    version = _version(project_id, "V1.0", "2026-01-01")
    fact = _fact(version, source_text=source_text)
    rule = _rule(version, fact)

    assert rule.rule_family == "study_treatment_adherence"
    assert rule.executor == "field_predicate"
    assert rule.required_domains == ("EX",)
    assert project_id not in rule.trigger_expression


def test_deterministic_evaluator_returns_original_protocol_text_and_record_values() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        service = MonitoringProtocolRuleService(repository)
        version = _version("proj_alpha", "V1.0", "2026-01-01")
        fact = _fact(version)
        rule = _rule(version, fact)

        result = service.evaluate_record(
            rule,
            {
                "SUBJID": "S01003",
                "EXDESC": "研究药物漏服 1 次",
                "date": "2026-07-12",
                "visit": "V3D8",
                "__source_locator__": "listing:EX:row:12",
            },
            observed_domains=["EX"],
        )

        assert result.matched is True
        assert result.evidence["EXDESC"] == "研究药物漏服 1 次"
        assert result.protocol_source["source_text"] == fact.source_text
        assert "方案原文" in result.protocol_source["primary_summary"]
        assert result.evidence_summary == "2026-07-12 V3D8 研究药物记录：研究药物漏服 1 次"


def test_deterministic_evaluator_fails_closed_when_required_domain_is_missing() -> None:
    with TemporaryDirectory() as directory:
        service = MonitoringProtocolRuleService(
            MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        )
        version = _version("proj_alpha", "V1.0", "2026-01-01")
        fact = _fact(version)
        rule = _rule(version, fact)

        result = service.evaluate_record(
            rule,
            {"SUBJID": "S01003", "EXDESC": "研究药物漏服 1 次"},
            observed_domains=["CM"],
        )

        assert result.matched is False
        assert result.missing_required_domains == ("EX",)
        assert "关键数据域缺失" in result.evidence_summary


def test_shadow_run_uses_gold_cases_without_creating_medical_risks() -> None:
    with TemporaryDirectory() as directory:
        repository = MonitoringProtocolRuleRepository(Path(directory) / "rules.sqlite3")
        repository.bind_gold_case_authority(lambda _case, _rule: None)
        service = MonitoringProtocolRuleService(repository)
        version = repository.register_protocol_version(
            _version(
                "proj_alpha",
                "V1.0",
                "2026-01-01",
                effective_from="2026-01-10",
            )
        )
        fact = repository.store_fact(_fact(version))
        rule = _rule(version, fact)
        _, pack, _ = _start_shadow_pack(repository, version, [rule])
        cases = (
            RuleGoldStandardCase.create(
                **_gold_case_source(rule, "positive")[1],
                project_id=version.project_id,
                rule_key=rule.rule_key,
                case_label="漏服记录应命中",
                input_record={"SUBJID": "GOLD-01", "EXDESC": "研究药物漏服 1 次"},
                observed_domains=["EX"],
                expected_match=True,
                medical_rationale="原始研究药物记录明确出现漏服描述。",
                evidence_locators=[_gold_case_source(rule, "positive")[0]],
            ),
            RuleGoldStandardCase.create(
                **_gold_case_source(rule, "negative")[1],
                project_id=version.project_id,
                rule_key=rule.rule_key,
                case_label="按计划服药不应命中",
                input_record={"SUBJID": "GOLD-02", "EXDESC": "按计划完成服药"},
                observed_domains=["EX"],
                expected_match=False,
                medical_rationale="记录未出现依从性异常。",
                evidence_locators=[_gold_case_source(rule, "negative")[0]],
            ),
        )
        assert repository.store_gold_cases(cases) == cases
        assert repository.store_gold_cases(cases) == cases

        run = service.run_shadow_validation(
            rule_pack_id=pack.rule_pack_id,
            batch_id="shadow-gold-v1",
        )

        assert run.case_count == 2
        assert run.passed_count == 2
        assert run.failed_count == 0
        assert len(repository.shadow_runs(version.project_id)) == 1
        assert repository.integrity_check() == "ok"


@pytest.mark.skipif(
    not (MY008_V3_AMENDMENT.exists() and MY008_V4_AMENDMENT.exists()),
    reason="MY008 real amendment documents are required",
)
def test_real_my008_amendments_expose_version_specific_monitoring_changes() -> None:
    v3_document = parse_protocol_docx(
        MY008_V3_AMENDMENT.name,
        MY008_V3_AMENDMENT.read_bytes(),
    )
    v4_document = parse_protocol_docx(
        MY008_V4_AMENDMENT.name,
        MY008_V4_AMENDMENT.read_bytes(),
    )

    v3_changes = extract_protocol_amendment_changes(v3_document)
    v4_changes = extract_protocol_amendment_changes(v4_document)
    v3_after = "\n".join(change.after_text for change in v3_changes)
    v4_after = "\n".join(change.after_text for change in v4_changes)

    assert len(v3_changes) >= 15
    assert "D6或D7" in v3_after
    assert "性激素检查" in v3_after
    assert "换药" in v3_after
    assert len(v4_changes) >= 7
    assert "EOP" in v4_after
    assert "撤药随访期" in v4_after
    assert all(change.source_locator.startswith("docx:table:") for change in v4_changes)


@pytest.mark.parametrize(
    "expression",
    (
        {
            "date_delta_range": {
                "field": "FIRST_IP_DTC",
                "other_field": "LAST_C5_DTC",
            }
        },
        {
            "ratio_range": {
                "numerator_field": "ACTUAL",
                "denominator_field": "PLANNED",
                "multiplier": 100,
                "min_value": 120,
                "max_value": 80,
            }
        },
        {
            "no_corresponding_record": {
                "domain": "AE",
                "match": [
                    {
                        "related_field": "SUBJID",
                        "current_field": "SUBJID",
                        "value": "forbidden-second-operand",
                    }
                ],
            }
        },
        {
            "no_corresponding_record": {
                "domain": "QS",
                "match": [
                    {
                        "related_field": "QSORRES",
                        "operator": "exists",
                        "value": "not-allowed",
                    }
                ],
            }
        },
    ),
)
def test_extended_dsl_rejects_incomplete_or_ambiguous_calculations(
    expression: dict[str, object],
) -> None:
    with pytest.raises(MonitoringProtocolRuleError):
        validate_predicate_expression(expression)


def test_canonical_lineage_rejects_duplicate_output_field_roles() -> None:
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="one canonical role",
    ):
        validate_rule_field_lineage(
            field_lineage={
                "subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:test:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
                "duplicate_subject_id": {
                    "field": "USUBJID",
                    "domain": "AE",
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            "listing:test:sheet:AE:header:1:field:USUBJID"
                        ),
                    },
                },
            },
            preconditions={"exists": {"field": "USUBJID"}},
            trigger_expression={"exists": {"field": "USUBJID"}},
            exclusions={},
            evidence_template="{USUBJID}",
            required_domains=("AE",),
        )


def _derived_unit_lineage(
    unit_contract: dict[str, str],
    *,
    input_roles: tuple[str, ...] = ("raw_value",),
) -> dict[str, Any]:
    return {
        "raw_value": {
            "field": "VALUE",
            "domain": "LB",
            "lineage": {
                "source_type": "raw_listing_field",
                "source_locator": "listing:test:sheet:LB:header:1:field:VALUE",
            },
        },
        "raw_unit": {
            "field": "UNIT",
            "domain": "LB",
            "lineage": {
                "source_type": "raw_listing_field",
                "source_locator": "listing:test:sheet:LB:header:1:field:UNIT",
            },
        },
        "derived_value": {
            "field": "DERIVED_VALUE",
            "domain": "LB",
            "lineage": {
                "source_type": "auditable_base_value",
                "input_field_roles": list(input_roles),
                "calculation_expression": "minimum(raw_value)",
                **unit_contract,
                "source_locator": (
                    "listing:test:derived:field:DERIVED_VALUE:header-source"
                ),
            },
        },
    }


@pytest.mark.parametrize(
    "unit_contract",
    (
        {"unit_literal": "U/L", "unit_field_role": "raw_unit"},
        {},
    ),
)
def test_canonical_lineage_rejects_non_exclusive_unit_contract(
    unit_contract: dict[str, str],
) -> None:
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="exactly one of unit_literal or unit_field_role",
    ):
        normalize_rule_field_lineage_units(
            _derived_unit_lineage(unit_contract)
        )


def test_canonical_lineage_rejects_unit_field_role_outside_inputs() -> None:
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="must reference one of its input_field_roles",
    ):
        normalize_rule_field_lineage_units(
            _derived_unit_lineage({"unit_field_role": "raw_unit"})
        )


def test_canonical_lineage_rejects_non_raw_unit_field_role() -> None:
    lineage = _derived_unit_lineage({"unit_literal": "U/L"})
    lineage["second_derived"] = {
        "field": "SECOND_DERIVED",
        "domain": "LB",
        "lineage": {
            "source_type": "auditable_base_value",
            "input_field_roles": ["derived_value"],
            "calculation_expression": "minimum(derived_value)",
            "unit_field_role": "derived_value",
            "source_locator": (
                "listing:test:derived:field:SECOND_DERIVED:header-source"
            ),
        },
    }
    with pytest.raises(
        MonitoringProtocolRuleError,
        match="inputs must be raw listing fields",
    ):
        normalize_rule_field_lineage_units(lineage)


def test_legacy_unit_is_read_only_normalized_without_fuzzy_matching() -> None:
    persisted_legacy = _derived_unit_lineage(
        {"unit": "raw_unit"},
        input_roles=("raw_value", "raw_unit"),
    )
    persisted_json = json.dumps(persisted_legacy, sort_keys=True)
    read_model = json.loads(persisted_json)
    by_role = normalize_rule_field_lineage_units(read_model)
    assert by_role["derived_value"]["lineage"]["unit_field_role"] == "raw_unit"
    assert "unit" not in by_role["derived_value"]["lineage"]
    assert '"unit": "raw_unit"' in persisted_json
    assert json.dumps(persisted_legacy, sort_keys=True) == persisted_json

    by_unique_field = normalize_rule_field_lineage_units(
        _derived_unit_lineage(
            {"unit": "UNIT"},
            input_roles=("raw_value", "raw_unit"),
        )
    )
    assert (
        by_unique_field["derived_value"]["lineage"]["unit_field_role"]
        == "raw_unit"
    )

    no_fuzzy_match = normalize_rule_field_lineage_units(
        _derived_unit_lineage(
            {"unit": "unit"},
            input_roles=("raw_value", "raw_unit"),
        )
    )
    assert no_fuzzy_match["derived_value"]["lineage"]["unit_literal"] == "unit"


def test_legacy_same_named_fields_across_domains_do_not_cross_link() -> None:
    lineage = _derived_unit_lineage(
        {"unit": "UNIT"},
        input_roles=("raw_value", "lb_unit", "vs_unit"),
    )
    lineage.pop("raw_unit")
    lineage["lb_unit"] = {
        "field": "UNIT",
        "domain": "LB",
        "lineage": {
            "source_type": "raw_listing_field",
            "source_locator": "listing:test:sheet:LB:header:1:field:UNIT",
        },
    }
    lineage["vs_unit"] = {
        "field": "UNIT",
        "domain": "VS",
        "lineage": {
            "source_type": "raw_listing_field",
            "source_locator": "listing:test:sheet:VS:header:1:field:UNIT",
        },
    }
    normalized = normalize_rule_field_lineage_units(lineage)
    assert normalized["derived_value"]["lineage"]["unit_literal"] == "UNIT"
    assert "unit_field_role" not in normalized["derived_value"]["lineage"]


def _rule_with_identity(
    base: MonitoringRuleDefinition,
    **identity: Any,
) -> MonitoringRuleDefinition:
    return MonitoringRuleDefinition.create(
        project_id=base.project_id,
        protocol_version_id=base.protocol_version_id,
        rule_key=base.rule_key,
        rule_family=base.rule_family,
        status=base.status,
        title=base.title,
        executor=base.executor,
        required_domains=base.required_domains,
        preconditions=base.preconditions,
        trigger_expression=base.trigger_expression,
        exclusions=base.exclusions,
        severity=base.severity,
        confidence=base.confidence,
        evidence_template=base.evidence_template,
        fact_revision_ids=base.fact_revision_ids,
        source_entry_id=base.source_entry_id,
        source_locator=base.source_locator,
        source_text=base.source_text,
        clinical_domain=base.clinical_domain,
        source_refs=base.source_refs,
        field_lineage=base.field_lineage,
        **identity,
    )


def _full_identity(**overrides: Any) -> dict[str, str]:
    identity = {
        "mapping_revision": "mapping-revision-001",
        "mapping_content_sha256": "a" * 64,
        "capability_manifest_sha256": "b" * 64,
        "effective_capabilities_sha256": "c" * 64,
        "recommendation_candidate_id": "candidate-001",
    }
    identity.update(overrides)
    return identity


def test_rule_identity_rejects_partial_or_malformed_material() -> None:
    version = _version(
        "proj_identity",
        "V1.0",
        "2026-01-01",
        effective_from="2026-01-10",
    )
    fact = _fact(version)
    base = _rule(
        version,
        fact,
        status="candidate",
        mapping_revision="",
        mapping_content_sha256="",
        capability_manifest_sha256="",
        effective_capabilities_sha256="",
    )

    with pytest.raises(MonitoringProtocolRuleError, match="partial rule identity"):
        _rule_with_identity(base, mapping_revision="mapping-revision-001")
    with pytest.raises(MonitoringProtocolRuleError, match="partial rule identity"):
        _rule_with_identity(base, recommendation_candidate_id="candidate-001")
    with pytest.raises(MonitoringProtocolRuleError, match="lowercase sha256"):
        _rule_with_identity(
            base,
            **_full_identity(mapping_content_sha256="A" * 64),
        )
    with pytest.raises(MonitoringProtocolRuleError, match="lowercase sha256"):
        _rule_with_identity(
            base,
            **_full_identity(capability_manifest_sha256="not-a-sha"),
        )
    for field in (
        "mapping_content_sha256",
        "capability_manifest_sha256",
        "effective_capabilities_sha256",
    ):
        for malformed in (f" {'a' * 64}", "A" * 64, 123):
            with pytest.raises(
                MonitoringProtocolRuleError,
                match="lowercase sha256",
            ):
                _rule_with_identity(
                    base,
                    **_full_identity(**{field: malformed}),
                )

    legacy = _rule_with_identity(base)
    assert legacy.rule_revision_id == base.rule_revision_id
    assert legacy.mapping_revision == ""
    assert legacy.mapping_content_sha256 == ""
    assert legacy.capability_manifest_sha256 == ""
    assert legacy.effective_capabilities_sha256 == ""
    assert legacy.recommendation_candidate_id == ""


def test_rule_identity_carries_fields_and_drives_revision_drift() -> None:
    version = _version(
        "proj_identity_drift",
        "V1.0",
        "2026-01-01",
        effective_from="2026-01-10",
    )
    fact = _fact(version)
    base = _rule(
        version,
        fact,
        status="candidate",
        mapping_revision="",
        mapping_content_sha256="",
        capability_manifest_sha256="",
        effective_capabilities_sha256="",
    )

    identified = _rule_with_identity(base, **_full_identity())
    assert identified.mapping_revision == "mapping-revision-001"
    assert identified.mapping_content_sha256 == "a" * 64
    assert identified.capability_manifest_sha256 == "b" * 64
    assert identified.effective_capabilities_sha256 == "c" * 64
    assert identified.recommendation_candidate_id == "candidate-001"
    assert identified.rule_revision_id != base.rule_revision_id
    assert identified.state_version == 1

    drifted = _rule_with_identity(
        base,
        **_full_identity(mapping_content_sha256="d" * 64),
    )
    assert drifted.rule_revision_id != identified.rule_revision_id

    public = identified.public_dict()
    assert public["mapping_revision"] == "mapping-revision-001"
    assert public["recommendation_candidate_id"] == "candidate-001"
