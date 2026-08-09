from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
    protocol_version_from_registered_source,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringRuleDefinition,
    ProtocolFact,
    RuleRiskBinding,
)
from services.api.app.protocol_text_extractor import (
    ProtocolTextDocument,
    parse_protocol_docx,
)
from services.api.app.source_intake import (
    SourceRegistryService,
    SourceRegistryStore,
)
from tests.test_monitoring_protocol_rules import _start_shadow_pack


MY008_V3 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/3.0/研究方案/"
    "MY008211A片-PNH-II&III期-长期安全性研究方案-V3.0-clean-20250530.docx"
)
MY008_V4 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/4.0/"
    "MY008211A片-PNH-II&III期-长期安全性研究方案-V4.0-clean-20260313.docx"
)


def _paragraph_text(document: ProtocolTextDocument, locator: str) -> str:
    return next(
        paragraph.text
        for paragraph in document.paragraphs
        if paragraph.source_locator == locator
    )


def _fact(
    *,
    version,
    key: str,
    fact_type: str,
    title: str,
    locator: str,
    text: str,
    payload: dict,
) -> ProtocolFact:
    return ProtocolFact.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_key=key,
        fact_type=fact_type,
        status="medically_confirmed",
        title=title,
        normalized_payload=payload,
        source_entry_id=version.source_entry_id,
        source_locator=locator,
        source_text=text,
    )


def _rule(
    *,
    version,
    fact: ProtocolFact,
    key: str,
    family: str,
    executor: str,
    domains: list[str],
    trigger: dict,
    title: str,
) -> MonitoringRuleDefinition:
    used_fields = {"SUBJID"}

    def collect(value):
        if isinstance(value, dict):
            for field_key, item in value.items():
                if field_key in {
                    "field",
                    "other_field",
                    "related_field",
                    "current_field",
                    "related_date_field",
                    "current_date_field",
                    "numerator_field",
                    "denominator_field",
                }:
                    used_fields.add(str(item))
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(trigger)
    schema_hash = sha256(
        f"{version.project_id}:my008-listing-schema".encode("utf-8")
    ).hexdigest()
    domain_by_field = {
        "C5_ENDDTC": "CM",
        "CMTRT": "CM",
        "IP_FIRST_DTC": "EX",
        "VISIT": "SV",
        "SUBJID": domains[0],
    }
    field_lineage = {}
    for index, field_name in enumerate(sorted(used_fields), start=1):
        domain = domain_by_field.get(field_name, domains[0])
        if field_name == "IP_FIRST_DTC":
            field_lineage["ip_date_raw"] = {
                "field": "EXSTDTC",
                "domain": "EX",
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        f"listing:{schema_hash}:sheet:EX:"
                        "header:1:field:EXSTDTC"
                    ),
                },
            }
            field_lineage["ip_first_date"] = {
                "field": field_name,
                "domain": "EX",
                "lineage": {
                    "source_type": "auditable_base_value",
                    "input_field_roles": ["ip_date_raw"],
                    "calculation_expression": "minimum(ip_date_raw)",
                    "unit": "ISO-8601 date",
                    "source_locator": (
                        f"listing:{schema_hash}:derived:field:IP_FIRST_DTC:"
                        "header-source"
                    ),
                },
            }
            continue
        field_lineage[f"raw_field_{index}"] = {
            "field": field_name,
            "domain": domain,
            "lineage": {
                "source_type": "raw_listing_field",
                "source_locator": (
                    f"listing:{schema_hash}:sheet:{domain}:"
                    f"header:1:field:{field_name}"
                ),
            },
        }
    return MonitoringRuleDefinition.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rule_key=key,
        rule_family=family,
        status="enabled",
        title=title,
        executor=executor,
        required_domains=domains,
        preconditions={"exists": {"field": "SUBJID"}},
        trigger_expression=trigger,
        exclusions={"missing": {"field": "SUBJID"}},
        severity="high",
        confidence="deterministic",
        evidence_template="{SUBJID}：确定性规则触发，需医学复核。",
        fact_revision_ids=[fact.fact_revision_id],
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
        clinical_domain=fact.clinical_domain,
        field_lineage=field_lineage,
        mapping_revision="my008-real-protocol-fixture-v1",
        mapping_content_sha256=schema_hash,
        capability_manifest_sha256=sha256(
            f"{version.project_id}:my008-capability-manifest".encode("utf-8")
        ).hexdigest(),
        effective_capabilities_sha256=sha256(
            f"{version.project_id}:my008-effective-capabilities".encode(
                "utf-8"
            )
        ).hexdigest(),
    )


@pytest.mark.skipif(
    not (MY008_V3.exists() and MY008_V4.exists()),
    reason="MY008 V3/V4 real protocols are required",
)
def test_real_my008_protocol_versions_drive_selective_rule_rereview() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source_registry = SourceRegistryService(
            SourceRegistryStore(root / "source_registry.jsonl")
        )
        repository = MonitoringProtocolRuleRepository(root / "rules.sqlite3")
        trusted_risk_ids = {"risk-c5", "risk-cm", "risk-visit"}
        service = MonitoringProtocolRuleService(
            repository,
            risk_binding_validator=lambda binding: (
                binding.risk_instance_id in trusted_risk_ids
            ),
        )

        v3_registration = source_registry.register_protocol_docx(
            "proj_my008_pnh",
            MY008_V3.name,
            MY008_V3.read_bytes(),
            module="medical_monitoring",
            expected_file_role="protocol",
        )
        v4_registration = source_registry.register_protocol_docx(
            "proj_my008_pnh",
            MY008_V4.name,
            MY008_V4.read_bytes(),
            module="medical_monitoring",
            expected_file_role="protocol",
        )
        v3 = repository.register_protocol_version(
            protocol_version_from_registered_source(
                project_id="proj_my008_pnh",
                protocol_code="MY008211A-PNH-2-03",
                    version_label="V3.0",
                    version_date="2025-05-30",
                    registration=v3_registration,
                    applicability_status="project_effective_confirmed",
                    operational_effective_from="2025-07-21",
                    operational_effective_to="2026-03-12",
                )
            )
        v4 = repository.register_protocol_version(
            protocol_version_from_registered_source(
                project_id="proj_my008_pnh",
                protocol_code="MY008211A-PNH-2-03",
                version_label="V4.0",
                    version_date="2026-03-13",
                    registration=v4_registration,
                    applicability_status="project_effective_confirmed",
                    operational_effective_from="2026-03-13",
                    predecessor_version_id=v3.protocol_version_id,
                )
        )
        v3_doc = parse_protocol_docx(MY008_V3.name, MY008_V3.read_bytes())
        v4_doc = parse_protocol_docx(MY008_V4.name, MY008_V4.read_bytes())

        shared_c5_locator = "docx:table:6:row:14:cell:1:paragraph:5"
        shared_cm_locator = "docx:table:6:row:22:cell:1:paragraph:11"
        v3_visit_locator = "docx:table:6:row:14:cell:1:paragraph:6"
        v4_visit_locator = "docx:table:6:row:14:cell:1:paragraph:6"

        v3_c5 = repository.store_fact(
            _fact(
                version=v3,
                key="study_treatment.transition.c5_to_my008",
                fact_type="study_treatment_regimen",
                title="C5 单抗转入研究药物的首次给药间隔",
                locator=shared_c5_locator,
                text=_paragraph_text(v3_doc, shared_c5_locator),
                payload={"minimum_days": 6, "maximum_days": 7},
            )
        )
        v4_c5 = repository.store_fact(
            _fact(
                version=v4,
                key="study_treatment.transition.c5_to_my008",
                fact_type="study_treatment_regimen",
                title="C5 单抗转入研究药物的首次给药间隔",
                locator=shared_c5_locator,
                text=_paragraph_text(v4_doc, shared_c5_locator),
                payload={"minimum_days": 6, "maximum_days": 7},
            )
        )
        v3_cm = repository.store_fact(
            _fact(
                version=v3,
                key="concomitant_medication.prohibited.complement_inhibitors",
                fact_type="concomitant_medication_prohibited",
                title="研究期间禁用其他补体抑制剂",
                locator=shared_cm_locator,
                text=_paragraph_text(v3_doc, shared_cm_locator),
                payload={"policy": "prohibited"},
            )
        )
        v4_cm = repository.store_fact(
            _fact(
                version=v4,
                key="concomitant_medication.prohibited.complement_inhibitors",
                fact_type="concomitant_medication_prohibited",
                title="研究期间禁用其他补体抑制剂",
                locator=shared_cm_locator,
                text=_paragraph_text(v4_doc, shared_cm_locator),
                payload={"policy": "prohibited"},
            )
        )
        v3_visit = repository.store_fact(
            _fact(
                version=v3,
                key="visit.withdrawal_followup.schedule",
                fact_type="visit_schedule",
                title="停药随访期访视",
                locator=v3_visit_locator,
                text=_paragraph_text(v3_doc, v3_visit_locator),
                payload={"required_visits": ["V10", "V11", "V12", "V13"]},
            )
        )
        v4_visit = repository.store_fact(
            _fact(
                version=v4,
                key="visit.withdrawal_followup.schedule",
                fact_type="visit_schedule",
                title="撤药随访期访视",
                locator=v4_visit_locator,
                text=_paragraph_text(v4_doc, v4_visit_locator),
                payload={"required_visits": ["VW1", "VW2", "VW3", "VW4"]},
                )
        )

        c5_trigger = {
            "not": {
                "date_delta_range": {
                    "field": "IP_FIRST_DTC",
                    "other_field": "C5_ENDDTC",
                    "min_days": 6,
                    "max_days": 7,
                }
            }
        }
        cm_trigger = {
            "regex": {
                "field": "CMTRT",
                "value": "补体.*(?:D因子|C3|C5|B因子)",
            }
        }
        v3_rules = [
            _rule(
                version=v3,
                fact=v3_c5,
                key="study_treatment.transition.c5_interval",
                family="cross_domain_consistency",
                executor="temporal",
                domains=["CM", "EX"],
                trigger=c5_trigger,
                title="C5 单抗转入研究药物间隔需复核",
            ),
            _rule(
                version=v3,
                fact=v3_cm,
                key="concomitant_medication.prohibited.complement_inhibitors",
                family="concomitant_medication_policy",
                executor="field_predicate",
                domains=["CM"],
                trigger=cm_trigger,
                title="禁用补体抑制剂需复核",
            ),
            _rule(
                version=v3,
                fact=v3_visit,
                key="visit.withdrawal_followup.completeness",
                family="visit_window_and_order",
                executor="cross_record",
                domains=["SV"],
                trigger={
                    "any": [
                        {
                            "no_corresponding_record": {
                                "domain": "SV",
                                "field": "VISIT",
                                "value": visit,
                            }
                        }
                        for visit in ("V10", "V11", "V12", "V13")
                    ]
                },
                title="停药随访访视完整性需复核",
            ),
        ]
        v4_rules = [
            _rule(
                version=v4,
                fact=v4_c5,
                key="study_treatment.transition.c5_interval",
                family="cross_domain_consistency",
                executor="temporal",
                domains=["CM", "EX"],
                trigger=c5_trigger,
                title="C5 单抗转入研究药物间隔需复核",
            ),
            _rule(
                version=v4,
                fact=v4_cm,
                key="concomitant_medication.prohibited.complement_inhibitors",
                family="concomitant_medication_policy",
                executor="field_predicate",
                domains=["CM"],
                trigger=cm_trigger,
                title="禁用补体抑制剂需复核",
            ),
            _rule(
                version=v4,
                fact=v4_visit,
                key="visit.withdrawal_followup.completeness",
                family="visit_window_and_order",
                executor="cross_record",
                domains=["SV"],
                trigger={
                    "any": [
                        {
                            "no_corresponding_record": {
                                "domain": "SV",
                                "field": "VISIT",
                                "value": visit,
                            }
                        }
                        for visit in ("VW1", "VW2", "VW3", "VW4")
                    ]
                },
                title="撤药随访访视完整性需复核",
            ),
        ]
        _v3_lifecycle, p3, _v3_confirmed_rules = _start_shadow_pack(
            repository,
            v3,
            v3_rules,
            clock="2025-07-21T00:00:00+08:00",
        )
        _v4_lifecycle, p4, _v4_confirmed_rules = _start_shadow_pack(
            repository,
            v4,
            v4_rules,
            clock="2026-03-13T00:00:00+08:00",
        )

        impact = service.compare_packs(p3.rule_pack_id, p4.rule_pack_id)

        assert impact.changed_rule_keys == (
            "visit.withdrawal_followup.completeness",
        )
        assert impact.unchanged_rule_keys == (
            "concomitant_medication.prohibited.complement_inhibitors",
            "study_treatment.transition.c5_interval",
        )
        bindings = [
            RuleRiskBinding(
                "risk-c5",
                v3.project_id,
                v3_rules[0].rule_key,
                v3_rules[0].rule_revision_id,
            ),
            RuleRiskBinding(
                "risk-cm",
                v3.project_id,
                v3_rules[1].rule_key,
                v3_rules[1].rule_revision_id,
            ),
            RuleRiskBinding(
                "risk-visit",
                v3.project_id,
                v3_rules[2].rule_key,
                v3_rules[2].rule_revision_id,
            ),
        ]
        tasks = service.schedule_re_reviews(
            previous_rule_pack_id=p3.rule_pack_id,
            current_rule_pack_id=p4.rule_pack_id,
            risk_bindings=bindings,
        )
        assert [task.risk_instance_id for task in tasks] == ["risk-visit"]

        c5_deviation = service.evaluate_record(
            v4_rules[0],
            {
                "SUBJID": "S01003",
                "C5_ENDDTC": "2026-01-01",
                "IP_FIRST_DTC": "2026-01-06",
                "__source_locator__": "listing:CM-EX:row:1",
            },
            observed_domains=["CM", "EX"],
        )
        c5_compliant = service.evaluate_record(
            v4_rules[0],
            {
                "SUBJID": "S01003",
                "C5_ENDDTC": "2026-01-01",
                "IP_FIRST_DTC": "2026-01-07",
                "__source_locator__": "listing:CM-EX:row:2",
            },
            observed_domains=["CM", "EX"],
        )
        cm_deviation = service.evaluate_record(
            v4_rules[1],
            {
                "SUBJID": "S01003",
                "CMTRT": "补体 C5 抑制剂",
                "__source_locator__": "listing:CM:row:3",
            },
            observed_domains=["CM"],
        )
        assert c5_deviation.matched is True
        assert c5_compliant.matched is False
        assert cm_deviation.matched is True
        assert repository.integrity_check() == "ok"
