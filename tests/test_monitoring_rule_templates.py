from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pytest

from services.api.app.listing_file_parser import parse_listing_file
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_protocol_rules import (
    RULE_FAMILIES,
    ProtocolFact,
    ProtocolSourceVersion,
)
from services.api.app.monitoring_rule_templates import (
    TEMPLATE_PAYLOAD_KEY,
    TEMPLATE_VERSION,
    MonitoringRuleTemplateError,
    compile_monitoring_rule_template,
    compile_monitoring_rule_templates,
    template_rule_families,
    try_compile_monitoring_rule_template,
)
from services.api.app.monitoring_source_fragment import resolve_protocol_fragment
from services.api.app.protocol_text_extractor import parse_protocol_docx


RUX_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
    "RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/"
    "V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
RUX_LISTING = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
MY009_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
MY009_LISTING = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
MY008_V3 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/3.0/研究方案/"
    "MY008211A片-PNH-II&III期-长期安全性研究方案-V3.0-clean-20250530.docx"
)
MY008_V4 = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/2-03/研究方案/4.0/"
    "MY008211A片-PNH-II&III期-长期安全性研究方案-V4.0-clean-20260313.docx"
)
D001_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/"
    "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
)

REAL_SOURCES = (
    RUX_PROTOCOL,
    RUX_LISTING,
    MY009_PROTOCOL,
    MY009_LISTING,
    MY008_V3,
    MY008_V4,
    D001_PROTOCOL,
)


@dataclass(frozen=True)
class GoldCase:
    fact: ProtocolFact
    positive: dict[str, Any]
    negative: dict[str, Any]
    boundary: dict[str, Any]
    observed_domains: tuple[str, ...]
    positive_related: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    negative_related: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    boundary_related: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _listing_header_locator(
    *,
    content_sha256: str,
    sheet_name: str,
    field_name: str,
) -> str:
    return (
        f"listing:{content_sha256}:sheet:{sheet_name}:"
        f"header:1:field:{field_name}"
    )


def _raw_lineage(source_locator: str) -> dict[str, Any]:
    return {
        "source_type": "raw_listing_field",
        "source_locator": source_locator,
    }


def _base_lineage(
    *,
    input_field_roles: tuple[str, ...],
    calculation_expression: str,
    unit_literal: str,
    source_locator: str,
) -> dict[str, Any]:
    return {
        "source_type": "auditable_base_value",
        "input_field_roles": list(input_field_roles),
        "calculation_expression": calculation_expression,
        "unit_literal": unit_literal,
        "source_locator": source_locator,
    }


def _fixture_raw_lineage(
    *,
    family: str,
    domain: str,
    field_name: str,
) -> dict[str, Any]:
    fixture_hash = sha256(f"{family}:{domain}".encode("utf-8")).hexdigest()
    return _raw_lineage(
        _listing_header_locator(
            content_sha256=fixture_hash,
            sheet_name=f"fixture-{domain}",
            field_name=field_name,
        )
    )


def _version(
    *,
    project_id: str,
    protocol_code: str,
    version_label: str,
    version_date: str,
    path: Path,
) -> ProtocolSourceVersion:
    return ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code=protocol_code,
        version_label=version_label,
        version_date=version_date,
        source_entry_id=f"source_{project_id}_{version_label.lower()}",
        source_title=path.name,
        content_sha256=sha256(path.read_bytes()).hexdigest(),
    )


def _symbolic_template(
    *,
    family: str,
    rule_key: str,
    executor: str,
    required_domains: tuple[str, ...],
    fields: dict[str, tuple[str, str]],
    trigger: dict[str, Any],
    title: str,
    lineages: dict[str, dict[str, Any]] | None = None,
    subtype: str = "",
    aesi_defined: bool = False,
    clinical_domain: str = "",
) -> dict[str, Any]:
    primary_domain = required_domains[0]
    field_specs = dict(fields)
    field_specs.setdefault("subject_id", ("SUBJID", primary_domain))
    lineage_overrides = lineages or {}
    assert set(lineage_overrides).issubset(field_specs)
    field_values = {
        role: {
            "field": field_name,
            "domain": domain,
            "lineage": dict(
                lineage_overrides.get(role)
                or _fixture_raw_lineage(
                    family=family,
                    domain=domain,
                    field_name=field_name,
                )
            ),
        }
        for role, (field_name, domain) in field_specs.items()
    }
    value = {
        "template_version": TEMPLATE_VERSION,
        "rule_family": family,
        "rule_key": rule_key,
        "executor": executor,
        "required_domains": list(required_domains),
        "listing_mapping": {
            "status": "medically_confirmed",
            "fields": field_values,
        },
        "preconditions": {"exists": {"field_role": "subject_id"}},
        "trigger_expression": trigger,
        "exclusions": {"missing": {"field_role": "subject_id"}},
        "title": title,
        "severity": "high",
        "evidence_template": "{subject_id}：确定性条件触发，需医学复核原始数据。",
    }
    if subtype:
        value["template_subtype"] = subtype
    if aesi_defined:
        value["aesi_defined"] = True
    if clinical_domain:
        value["clinical_domain"] = clinical_domain
    return value


def _fact(
    *,
    version: ProtocolSourceVersion,
    fact_key: str,
    fact_type: str,
    title: str,
    source_entry_id: str,
    source_locator: str,
    source_text: str,
    template: dict[str, Any],
) -> ProtocolFact:
    return ProtocolFact.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_key=fact_key,
        fact_type=fact_type,
        status="medically_confirmed",
        title=title,
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id=source_entry_id,
        source_locator=source_locator,
        source_text=source_text,
    )


def _fragment(document: Any, locator: str) -> str:
    value = resolve_protocol_fragment(document, locator)["text"]
    assert value
    return value


def _enabled_for_template_evaluation(
    rule: Any,
) -> Any:
    assert rule.status == "candidate"
    return replace(rule, status="enabled")


@pytest.fixture(scope="module")
def gold_matrix() -> dict[str, GoldCase]:
    if not all(path.exists() for path in REAL_SOURCES):
        pytest.skip("real protocols and RUX/MY009 listings are required")

    documents = {
        "rux": parse_protocol_docx(RUX_PROTOCOL.name, RUX_PROTOCOL.read_bytes()),
        "my009": parse_protocol_docx(
            MY009_PROTOCOL.name, MY009_PROTOCOL.read_bytes()
        ),
        "my008_v3": parse_protocol_docx(MY008_V3.name, MY008_V3.read_bytes()),
        "my008_v4": parse_protocol_docx(MY008_V4.name, MY008_V4.read_bytes()),
        "d001": parse_protocol_docx(
            D001_PROTOCOL.name, D001_PROTOCOL.read_bytes()
        ),
    }
    versions = {
        "rux": _version(
            project_id="proj_rux_03_002",
            protocol_code="RUX-03-002",
            version_label="V1.3",
            version_date="2024-08-14",
            path=RUX_PROTOCOL,
        ),
        "my009": _version(
            project_id="proj_my009_uc",
            protocol_code="MY009-UC-2-01",
            version_label="V3.0",
            version_date="2025-09-26",
            path=MY009_PROTOCOL,
        ),
        "my008": _version(
            project_id="proj_my008_pnh",
            protocol_code="MY008211A-PNH-2-03",
            version_label="V4.0",
            version_date="2026-03-13",
            path=MY008_V4,
        ),
        "d001": _version(
            project_id="proj_d001",
            protocol_code="CMS-D001",
            version_label="V1.0",
            version_date="2025-12-21",
            path=D001_PROTOCOL,
        ),
    }

    rux_listing_bytes = RUX_LISTING.read_bytes()
    my009_listing_bytes = MY009_LISTING.read_bytes()
    rux_listing_sha256 = sha256(rux_listing_bytes).hexdigest()
    my009_listing_sha256 = sha256(my009_listing_bytes).hexdigest()
    rux_sheets = parse_listing_file(RUX_LISTING.name, rux_listing_bytes)
    my009_sheets = parse_listing_file(MY009_LISTING.name, my009_listing_bytes)
    rux_ae = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("AE--")
    )
    rux_mh = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("MH--")
    )
    rux_lb = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("LBCHEM--")
    )
    rux_sv = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("SV--")
    )
    rux_iga = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("IGA--")
    )
    rux_eca = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("ECA--")
    )
    rux_ecb = next(
        sheet for sheet in rux_sheets if sheet.sheet_name.startswith("ECB--")
    )
    my009_cm = next(sheet for sheet in my009_sheets if sheet.sheet_name == "CM")
    rux_lb_headers = tuple(rux_lb.rows[0])
    assert {
        "SUBJID",
        "LBDAT",
        "LBTEST",
        "LBORRES",
        "LBORRESU",
        "LBORNRLO",
        "LBORNRHI",
    }.issubset(rux_lb_headers)

    source_specs = {
        "ae_mh_missing_review": (
            "rux",
            "docx:paragraph:1285",
            "safety_assessment",
            "safety.ae_mh.collection_boundary",
        ),
        "cs_ncs_review": (
            "rux",
            "docx:paragraph:1036",
            "safety_assessment",
            "safety.cs_ncs.assessment",
        ),
        "study_treatment_change": (
            "my008_v4",
            "docx:table:6:row:14:cell:1:paragraph:5",
            "study_treatment_change",
            "study_treatment.transition.c5_interval",
        ),
        "study_treatment_adherence": (
            "rux",
            "docx:paragraph:1014",
            "study_treatment_adherence",
            "study_treatment.adherence.range",
        ),
        "concomitant_medication_policy": (
            "my009",
            "docx:paragraph:1110",
            "concomitant_medication_prohibited",
            "concomitant_medication.prohibited.biologic",
        ),
        "visit_window_and_order": (
            "my008_v4",
            "docx:table:6:row:14:cell:1:paragraph:6",
            "visit_window",
            "visit.withdrawal.followup_window",
        ),
        "eligibility_continuity": (
            "d001",
            "docx:table:4:row:7:cell:1:paragraph:6",
            "eligibility_inclusion",
            "eligibility.pasi.minimum",
        ),
        "ae_sae_aesi_consistency": (
            "my008_v4",
            "docx:paragraph:1140",
            "aesi_definition",
            "safety.aesi.definition",
        ),
        "efficacy_endpoint_completeness": (
            "rux",
            "docx:table:1:row:9:cell:0:paragraph:2",
            "efficacy_assessment",
            "efficacy.iga_ts.week8",
        ),
        "cross_domain_consistency": (
            "d001",
            "docx:paragraph:1845",
            "protocol_deviation",
            "protocol_deviation.rescue_ip_chain",
        ),
    }

    template_specs: dict[str, dict[str, Any]] = {
        "ae_mh_missing_review": {
            "version": versions["rux"],
            "domains": ("AE", "EC", "MH"),
            "fields": {
                "subject_id": ("SUBJID", "AE"),
                "event_term": ("AETERM", "AE"),
                "event_date": ("AESTDAT", "AE"),
                "first_dose_date": ("FIRSTDOSEDAT", "AE"),
                "mh_subject_id": ("SUBJID", "MH"),
                "mh_term": ("MHTERM", "MH"),
                "mh_date": ("MHSTDAT", "MH"),
                "administration_date": ("ECADAT", "EC"),
            },
            "lineages": {
                "subject_id": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ae.sheet_name,
                        field_name="SUBJID",
                    )
                ),
                "event_term": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ae.sheet_name,
                        field_name="AETERM",
                    )
                ),
                "event_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ae.sheet_name,
                        field_name="AESTDAT",
                    )
                ),
                "first_dose_date": _base_lineage(
                    input_field_roles=("administration_date",),
                    calculation_expression="minimum(administration_date)",
                    unit_literal="ISO-8601 date",
                    source_locator=(
                        f"derived-listing:{rux_listing_sha256}:"
                        "field:FIRSTDOSEDAT"
                    ),
                ),
                "mh_subject_id": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_mh.sheet_name,
                        field_name="SUBJID",
                    )
                ),
                "mh_term": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_mh.sheet_name,
                        field_name="MHTERM",
                    )
                ),
                "mh_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_mh.sheet_name,
                        field_name="MHSTDAT",
                    )
                ),
                "administration_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_eca.sheet_name,
                        field_name="ECADAT",
                    )
                ),
            },
            "trigger": {
                "all": [
                    {
                        "date_compare": {
                            "field_role": "event_date",
                            "other_field_role": "first_dose_date",
                            "relation": "before",
                        }
                    },
                    {
                        "no_corresponding_record": {
                            "domain": "MH",
                            "match": [
                                {
                                    "related_field_role": "mh_subject_id",
                                    "current_field_role": "subject_id",
                                },
                                {
                                    "related_field_role": "mh_term",
                                    "current_field_role": "event_term",
                                },
                            ],
                            "date_window": {
                                "related_date_field_role": "mh_date",
                                "current_date_field_role": "event_date",
                                "min_days": 0,
                                "max_days": 0,
                            },
                        }
                    },
                ]
            },
            "positive": {
                "SUBJID": "GOLD-AE-01",
                "AETERM": "过敏性鼻炎",
                "AESTDAT": "2025-01-09",
                "FIRSTDOSEDAT": "2025-01-10",
            },
            "negative": {
                "SUBJID": "GOLD-AE-02",
                "AETERM": "过敏性鼻炎",
                "AESTDAT": "2025-01-09",
                "FIRSTDOSEDAT": "2025-01-10",
            },
            "negative_related": {
                "MH": [
                    {
                        "SUBJID": "GOLD-AE-02",
                        "MHTERM": "过敏性鼻炎",
                        "MHSTDAT": "2025-01-09",
                        "__source_locator__": "gold:ae_mh:mh:negative",
                    }
                ]
            },
            "positive_related": {"MH": []},
            "boundary": {
                "SUBJID": "GOLD-AE-03",
                "AETERM": "头痛",
                "AESTDAT": "2025-01-10",
                "FIRSTDOSEDAT": "2025-01-10",
            },
        },
        "cs_ncs_review": {
            "version": versions["rux"],
            "domains": ("LB",),
            "fields": {
                "subject_id": ("SUBJID", "LB"),
                "abnormal_flag": ("LBNRIND", "LB"),
                "clinical_significance": ("LBCLSIGN", "LB"),
            },
            "lineages": {
                role: _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_lb.sheet_name,
                        field_name=field_name,
                    )
                )
                for role, field_name in {
                    "subject_id": "SUBJID",
                    "abnormal_flag": "LBNRIND",
                    "clinical_significance": "LBCLSIGN",
                }.items()
            },
            "trigger": {
                "all": [
                    {
                        "in": {
                            "field_role": "abnormal_flag",
                            "value": ["H", "L", "ABNORMAL"],
                        }
                    },
                    {
                        "missing": {"field_role": "clinical_significance"}
                    },
                ]
            },
            "positive": {
                "SUBJID": "GOLD-CS-01",
                "LBNRIND": "H",
                "LBCLSIGN": "",
            },
            "negative": {
                "SUBJID": "GOLD-CS-02",
                "LBNRIND": "H",
                "LBCLSIGN": "NCS",
            },
            "boundary": {
                "SUBJID": "GOLD-CS-03",
                "LBNRIND": "NORMAL",
                "LBCLSIGN": "",
            },
        },
        "study_treatment_change": {
            "version": versions["my008"],
            "domains": ("EX",),
            "fields": {
                "subject_id": ("USUBJID", "EX"),
                "last_c5_date": ("LAST_C5_DTC", "EX"),
                "first_ip_date": ("FIRST_IP_DTC", "EX"),
            },
            "trigger": {
                "not": {
                    "date_delta_range": {
                        "field_role": "first_ip_date",
                        "other_field_role": "last_c5_date",
                        "min_days": 6,
                        "max_days": 7,
                    }
                }
            },
            "positive": {
                "USUBJID": "GOLD-IP-01",
                "LAST_C5_DTC": "2025-01-01",
                "FIRST_IP_DTC": "2025-01-06",
            },
            "negative": {
                "USUBJID": "GOLD-IP-02",
                "LAST_C5_DTC": "2025-01-01",
                "FIRST_IP_DTC": "2025-01-07",
            },
            "boundary": {
                "USUBJID": "GOLD-IP-03",
                "LAST_C5_DTC": "2025-01-01",
                "FIRST_IP_DTC": "2025-01-08",
            },
        },
        "study_treatment_adherence": {
            "version": versions["rux"],
            "domains": ("EC",),
            "fields": {
                "subject_id": ("SUBJID", "EC"),
                "actual_doses": ("ECACTNUM", "EC"),
                "planned_doses": ("ECPLANNUM", "EC"),
                "actual_dose_date": ("ECADAT", "EC"),
                "planned_frequency": ("ECBDOFRQ", "EC"),
                "planned_start_date": ("ECBSTDAT", "EC"),
                "planned_end_date": ("ECBENDAT", "EC"),
            },
            "lineages": {
                "subject_id": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_eca.sheet_name,
                        field_name="SUBJID",
                    )
                ),
                "actual_doses": _base_lineage(
                    input_field_roles=("actual_dose_date",),
                    calculation_expression="count_non_missing(actual_dose_date)",
                    unit_literal="dose count",
                    source_locator=(
                        f"derived-listing:{rux_listing_sha256}:field:ECACTNUM"
                    ),
                ),
                "planned_doses": _base_lineage(
                    input_field_roles=(
                        "planned_frequency",
                        "planned_start_date",
                        "planned_end_date",
                    ),
                    calculation_expression=(
                        "scheduled_dose_count(planned_frequency, "
                        "planned_start_date, planned_end_date)"
                    ),
                    unit_literal="dose count",
                    source_locator=(
                        f"derived-listing:{rux_listing_sha256}:field:ECPLANNUM"
                    ),
                ),
                "actual_dose_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_eca.sheet_name,
                        field_name="ECADAT",
                    )
                ),
                "planned_frequency": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ecb.sheet_name,
                        field_name="ECBDOFRQ",
                    )
                ),
                "planned_start_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ecb.sheet_name,
                        field_name="ECBSTDAT",
                    )
                ),
                "planned_end_date": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_ecb.sheet_name,
                        field_name="ECBENDAT",
                    )
                ),
            },
            "trigger": {
                "all": [
                    {"gt": {"field_role": "planned_doses", "value": 0}},
                    {
                        "not": {
                            "ratio_range": {
                                "numerator_field_role": "actual_doses",
                                "denominator_field_role": "planned_doses",
                                "multiplier": 100,
                                "min_value": 80,
                                "max_value": 120,
                            }
                        }
                    },
                ]
            },
            "positive": {
                "SUBJID": "GOLD-ADH-01",
                "ECACTNUM": 7,
                "ECPLANNUM": 10,
            },
            "negative": {
                "SUBJID": "GOLD-ADH-02",
                "ECACTNUM": 10,
                "ECPLANNUM": 10,
            },
            "boundary": {
                "SUBJID": "GOLD-ADH-03",
                "ECACTNUM": 8,
                "ECPLANNUM": 10,
            },
        },
        "concomitant_medication_policy": {
            "version": versions["my009"],
            "domains": ("CM",),
            "fields": {
                "subject_id": ("USUBJID", "CM"),
                "medication_name": ("CMTRT", "CM"),
            },
            "lineages": {
                role: _raw_lineage(
                    _listing_header_locator(
                        content_sha256=my009_listing_sha256,
                        sheet_name=my009_cm.sheet_name,
                        field_name=field_name,
                    )
                )
                for role, field_name in {
                    "subject_id": "USUBJID",
                    "medication_name": "CMTRT",
                }.items()
            },
            "trigger": {
                "regex": {
                    "field_role": "medication_name",
                    "value": "(?:生物制剂|JAK抑制剂|S1PR调节剂)",
                }
            },
            "positive": {"USUBJID": "GOLD-CM-01", "CMTRT": "示例JAK抑制剂"},
            "negative": {"USUBJID": "GOLD-CM-02", "CMTRT": "维生素D"},
            "boundary": {"USUBJID": "GOLD-CM-03", "CMTRT": "外用保湿剂"},
        },
        "visit_window_and_order": {
            "version": versions["my008"],
            "domains": ("SV",),
            "fields": {
                "subject_id": ("USUBJID", "SV"),
                "actual_visit_date": ("SVSTDTC", "SV"),
                "reference_visit_date": ("SVREFDTC", "SV"),
            },
            "trigger": {
                "not": {
                    "date_delta_range": {
                        "field_role": "actual_visit_date",
                        "other_field_role": "reference_visit_date",
                        "min_days": -28,
                        "max_days": 28,
                    }
                }
            },
            "positive": {
                "USUBJID": "GOLD-SV-01",
                "SVSTDTC": "2025-02-01",
                "SVREFDTC": "2025-01-03",
            },
            "negative": {
                "USUBJID": "GOLD-SV-02",
                "SVSTDTC": "2025-01-30",
                "SVREFDTC": "2025-01-03",
            },
            "boundary": {
                "USUBJID": "GOLD-SV-03",
                "SVSTDTC": "2025-01-31",
                "SVREFDTC": "2025-01-03",
            },
        },
        "eligibility_continuity": {
            "version": versions["d001"],
            "domains": ("IE",),
            "fields": {
                "subject_id": ("SUBJID", "IE"),
                "pasi_score": ("PASI_SCORE", "IE"),
            },
            "trigger": {"lt": {"field_role": "pasi_score", "value": 12}},
            "positive": {"SUBJID": "GOLD-IE-01", "PASI_SCORE": 11.9},
            "negative": {"SUBJID": "GOLD-IE-02", "PASI_SCORE": 15},
            "boundary": {"SUBJID": "GOLD-IE-03", "PASI_SCORE": 12},
        },
        "ae_sae_aesi_consistency": {
            "version": versions["my008"],
            "domains": ("AE", "AESI"),
            "fields": {
                "subject_id": ("USUBJID", "AE"),
                "ae_sequence": ("AESEQ", "AE"),
                "event_term": ("AETERM", "AE"),
                "aesi_subject_id": ("USUBJID", "AESI"),
                "aesi_ae_sequence": ("AESIAESEQ", "AESI"),
                "aesi_report_date": ("AESIREPDTC", "AESI"),
            },
            "trigger": {
                "all": [
                    {
                        "regex": {
                            "field_role": "event_term",
                            "value": "(?:突破性溶血|荚膜细菌感染)",
                        }
                    },
                    {
                        "no_corresponding_record": {
                            "domain": "AESI",
                            "match": [
                                {
                                    "related_field_role": "aesi_subject_id",
                                    "current_field_role": "subject_id",
                                },
                                {
                                    "related_field_role": "aesi_ae_sequence",
                                    "current_field_role": "ae_sequence",
                                },
                                {
                                    "related_field_role": "aesi_report_date",
                                    "operator": "exists",
                                },
                            ],
                        }
                    },
                ]
            },
            "positive": {
                "USUBJID": "GOLD-AESI-01",
                "AESEQ": "7",
                "AETERM": "临床突破性溶血",
            },
            "negative": {
                "USUBJID": "GOLD-AESI-02",
                "AESEQ": "8",
                "AETERM": "荚膜细菌感染",
            },
            "negative_related": {
                "AESI": [
                    {
                        "USUBJID": "GOLD-AESI-02",
                        "AESIAESEQ": "8",
                        "AESIREPDTC": "2025-01-02",
                        "__source_locator__": "gold:aesi:negative",
                    }
                ]
            },
            "positive_related": {"AESI": []},
            "boundary": {
                "USUBJID": "GOLD-AESI-03",
                "AESEQ": "9",
                "AETERM": "头痛",
            },
            "subtype": "aesi",
            "aesi_defined": True,
        },
        "efficacy_endpoint_completeness": {
            "version": versions["rux"],
            "domains": ("QS", "SV"),
            "fields": {
                "subject_id": ("SUBJID", "SV"),
                "target_visit": ("VISIT", "SV"),
                "qs_subject_id": ("SUBJID", "QS"),
                "qs_visit": ("VISIT", "QS"),
                "assessment_code": ("FORMOID", "QS"),
                "assessment_result": ("IGASCORE", "QS"),
            },
            "lineages": {
                "subject_id": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_sv.sheet_name,
                        field_name="SUBJID",
                    )
                ),
                "target_visit": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_sv.sheet_name,
                        field_name="VISIT",
                    )
                ),
                "qs_subject_id": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_iga.sheet_name,
                        field_name="SUBJID",
                    )
                ),
                "qs_visit": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_iga.sheet_name,
                        field_name="VISIT",
                    )
                ),
                "assessment_code": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_iga.sheet_name,
                        field_name="FORMOID",
                    )
                ),
                "assessment_result": _raw_lineage(
                    _listing_header_locator(
                        content_sha256=rux_listing_sha256,
                        sheet_name=rux_iga.sheet_name,
                        field_name="IGASCORE",
                    )
                ),
            },
            "trigger": {
                "all": [
                    {"eq": {"field_role": "target_visit", "value": "W8"}},
                    {
                        "no_corresponding_record": {
                            "domain": "QS",
                            "match": [
                                {
                                    "related_field_role": "qs_subject_id",
                                    "current_field_role": "subject_id",
                                },
                                {
                                    "related_field_role": "qs_visit",
                                    "current_field_role": "target_visit",
                                },
                                {
                                    "related_field_role": "assessment_code",
                                    "value": "IGA",
                                },
                                {
                                    "related_field_role": "assessment_result",
                                    "operator": "exists",
                                },
                            ],
                        }
                    },
                ]
            },
            "positive": {"SUBJID": "GOLD-EFF-01", "VISIT": "W8"},
            "negative": {"SUBJID": "GOLD-EFF-02", "VISIT": "W8"},
            "negative_related": {
                "QS": [
                    {
                        "SUBJID": "GOLD-EFF-02",
                        "VISIT": "W8",
                        "FORMOID": "IGA",
                        "IGASCORE": "1",
                        "__source_locator__": "gold:endpoint:negative",
                    }
                ]
            },
            "positive_related": {"QS": []},
            "boundary": {"SUBJID": "GOLD-EFF-03", "VISIT": "W7"},
        },
        "cross_domain_consistency": {
            "version": versions["d001"],
            "domains": ("CM", "EX", "AE", "DV"),
            "fields": {
                "subject_id": ("SUBJID", "CM"),
                "rescue_name": ("CMTRT", "CM"),
                "rescue_date": ("CMSTDAT", "CM"),
                "ex_subject_id": ("SUBJID", "EX"),
                "ex_action": ("EXACTION", "EX"),
                "ex_date": ("EXSTDAT", "EX"),
                "ae_subject_id": ("SUBJID", "AE"),
                "ae_date": ("AESTDAT", "AE"),
                "dv_subject_id": ("SUBJID", "DV"),
                "dv_date": ("DVSTDAT", "DV"),
            },
            "trigger": {
                "all": [
                    {
                        "regex": {
                            "field_role": "rescue_name",
                            "value": "(?:系统性补救治疗|补救药物)",
                        }
                    },
                    {
                        "any": [
                            {
                                "no_corresponding_record": {
                                    "domain": "EX",
                                    "match": [
                                        {
                                            "related_field_role": "ex_subject_id",
                                            "current_field_role": "subject_id",
                                        },
                                        {
                                            "related_field_role": "ex_action",
                                            "value": ["暂停", "停药"],
                                            "operator": "in",
                                        },
                                    ],
                                    "date_window": {
                                        "related_date_field_role": "ex_date",
                                        "current_date_field_role": "rescue_date",
                                        "min_days": 0,
                                        "max_days": 0,
                                    },
                                }
                            },
                            {
                                "all": [
                                    {
                                        "no_corresponding_record": {
                                            "domain": "AE",
                                            "match": [
                                                {
                                                    "related_field_role": "ae_subject_id",
                                                    "current_field_role": "subject_id",
                                                }
                                            ],
                                            "date_window": {
                                                "related_date_field_role": "ae_date",
                                                "current_date_field_role": "rescue_date",
                                                "min_days": 0,
                                                "max_days": 0,
                                            },
                                        }
                                    },
                                    {
                                        "no_corresponding_record": {
                                            "domain": "DV",
                                            "match": [
                                                {
                                                    "related_field_role": "dv_subject_id",
                                                    "current_field_role": "subject_id",
                                                }
                                            ],
                                            "date_window": {
                                                "related_date_field_role": "dv_date",
                                                "current_date_field_role": "rescue_date",
                                                "min_days": 0,
                                                "max_days": 0,
                                            },
                                        }
                                    },
                                ]
                            },
                        ]
                    },
                ]
            },
            "positive": {
                "SUBJID": "GOLD-XD-01",
                "CMTRT": "系统性补救治疗",
                "CMSTDAT": "2025-01-10",
            },
            "negative": {
                "SUBJID": "GOLD-XD-02",
                "CMTRT": "系统性补救治疗",
                "CMSTDAT": "2025-01-10",
            },
            "negative_related": {
                "EX": [
                    {
                        "SUBJID": "GOLD-XD-02",
                        "EXACTION": "暂停",
                        "EXSTDAT": "2025-01-10",
                        "__source_locator__": "gold:cross:ex:negative",
                    }
                ],
                "AE": [
                    {
                        "SUBJID": "GOLD-XD-02",
                        "AESTDAT": "2025-01-10",
                        "__source_locator__": "gold:cross:ae:negative",
                    }
                ],
                "DV": [],
            },
            "boundary": {
                "SUBJID": "GOLD-XD-03",
                "CMTRT": "系统性补救治疗",
                "CMSTDAT": "2025-01-10",
            },
            "boundary_related": {
                "EX": [
                    {
                        "SUBJID": "GOLD-XD-03",
                        "EXACTION": "停药",
                        "EXSTDAT": "2025-01-10",
                    }
                ],
                "DV": [
                    {
                        "SUBJID": "GOLD-XD-03",
                        "DVSTDAT": "2025-01-10",
                    }
                ],
                "AE": [],
            },
            "positive_related": {"EX": [], "AE": [], "DV": []},
            "clinical_domain": "protocol_deviation",
        },
    }

    matrix: dict[str, GoldCase] = {}
    for family, config in template_specs.items():
        source_key, locator, fact_type, fact_key = source_specs[family]
        source_doc = documents[source_key]
        template = _symbolic_template(
            family=family,
            rule_key=f"template.{family}.minimum",
            executor=(
                "temporal"
                if family in {"study_treatment_change", "visit_window_and_order"}
                else "field_predicate"
            ),
            required_domains=config["domains"],
            fields=dict(config["fields"]),
            trigger=config["trigger"],
            title=f"{family} 需医学复核候选",
            lineages=config.get("lineages"),
            subtype=config.get("subtype", ""),
            aesi_defined=config.get("aesi_defined", False),
            clinical_domain=config.get("clinical_domain", ""),
        )
        fact = _fact(
            version=config["version"],
            fact_key=fact_key,
            fact_type=fact_type,
            title=family,
            source_entry_id=config["version"].source_entry_id,
            source_locator=locator,
            source_text=_fragment(source_doc, locator),
            template=template,
        )
        matrix[family] = GoldCase(
            fact=fact,
            positive={
                **config["positive"],
                "__source_locator__": f"gold:{family}:positive",
            },
            negative=config["negative"],
            boundary=config["boundary"],
            observed_domains=config["domains"],
            positive_related=config.get("positive_related", {}),
            negative_related=config.get("negative_related", {}),
            boundary_related=config.get("boundary_related", {}),
        )

    data_quality_template = _symbolic_template(
        family="data_quality",
        rule_key="template.data_quality.required_fields",
        executor="field_predicate",
        required_domains=("LB",),
        fields={
            "subject_id": ("SUBJID", "LB"),
            "result_date": ("LBDAT", "LB"),
            "result_value": ("LBORRES", "LB"),
            "result_unit": ("LBORRESU", "LB"),
            "reference_low": ("LBORNRLO", "LB"),
            "reference_high": ("LBORNRHI", "LB"),
        },
        lineages={
            role: _raw_lineage(
                _listing_header_locator(
                    content_sha256=rux_listing_sha256,
                    sheet_name=rux_lb.sheet_name,
                    field_name=field_name,
                )
            )
            for role, field_name in {
                "subject_id": "SUBJID",
                "result_date": "LBDAT",
                "result_value": "LBORRES",
                "result_unit": "LBORRESU",
                "reference_low": "LBORNRLO",
                "reference_high": "LBORNRHI",
            }.items()
        },
        trigger={
            "any": [
                {"missing": {"field_role": "result_date"}},
                {"missing": {"field_role": "result_value"}},
                {"missing": {"field_role": "result_unit"}},
                {"missing": {"field_role": "reference_low"}},
                {"missing": {"field_role": "reference_high"}},
            ]
        },
        title="实验室原始字段完整性需医学复核候选",
    )
    data_quality_fact = _fact(
        version=versions["rux"],
        fact_key="data_quality.lb.confirmed_mapping",
        fact_type="data_quality",
        title="RUX 实验室 Listing 已确认字段映射",
        source_entry_id="source_rux_listing_20250612",
        source_locator=(
            f"listing-mapping:{rux_listing_sha256}:"
            f"sheet:{rux_lb.sheet_name}:header"
        ),
        source_text=" | ".join(rux_lb_headers),
        template=data_quality_template,
    )
    matrix["data_quality"] = GoldCase(
        fact=data_quality_fact,
        positive={
            "SUBJID": "GOLD-DQ-01",
            "LBDAT": "2025-01-01",
            "LBORRES": "10",
            "LBORRESU": "",
            "LBORNRLO": "0",
            "LBORNRHI": "20",
            "__source_locator__": "gold:data_quality:positive",
        },
        negative={
            "SUBJID": "GOLD-DQ-02",
            "LBDAT": "2025-01-01",
            "LBORRES": "10",
            "LBORRESU": "U/L",
            "LBORNRLO": "0",
            "LBORNRHI": "20",
        },
        boundary={
            "SUBJID": "GOLD-DQ-03",
            "LBDAT": "2025-01-01",
            "LBORRES": "0",
            "LBORRESU": "U/L",
            "LBORNRLO": "0",
            "LBORNRHI": "0",
        },
        observed_domains=("LB",),
    )

    v3_text = _fragment(
        documents["my008_v3"],
        "docx:table:6:row:14:cell:1:paragraph:6",
    )
    v4_text = _fragment(
        documents["my008_v4"],
        "docx:table:6:row:14:cell:1:paragraph:6",
    )
    assert "访视10" in v3_text
    assert "访视W1" in v4_text
    assert v3_text != v4_text
    return matrix


def test_template_catalog_covers_every_rule_family() -> None:
    assert set(template_rule_families()) == set(RULE_FAMILIES)


def test_four_real_projects_compile_all_eleven_rule_families_with_source_trace(
    gold_matrix: dict[str, GoldCase],
) -> None:
    rules = compile_monitoring_rule_templates(
        case.fact for case in gold_matrix.values()
    )
    assert {rule.rule_family for rule in rules} == set(RULE_FAMILIES)
    assert {rule.project_id for rule in rules} == {
        "proj_rux_03_002",
        "proj_my009_uc",
        "proj_my008_pnh",
        "proj_d001",
    }
    for rule in rules:
        case = gold_matrix[rule.rule_family]
        assert rule.status == "candidate"
        assert rule.source_locator == case.fact.source_locator
        assert rule.source_text == case.fact.source_text
        assert rule.source_refs[0].fact_revision_id == case.fact.fact_revision_id
        assert rule.field_lineage == case.fact.normalized_payload[
            TEMPLATE_PAYLOAD_KEY
        ]["listing_mapping"]["fields"]
        assert "医学复核" in rule.title


@pytest.mark.parametrize("family", RULE_FAMILIES)
def test_each_template_has_positive_negative_missing_boundary_and_raw_locator_gold_cases(
    family: str,
    gold_matrix: dict[str, GoldCase],
) -> None:
    case = gold_matrix[family]
    rule = _enabled_for_template_evaluation(
        compile_monitoring_rule_template(case.fact)
    )
    service = object.__new__(MonitoringProtocolRuleService)

    positive = service.evaluate_record(
        rule,
        case.positive,
        observed_domains=case.observed_domains,
        related_records=case.positive_related,
    )
    negative = service.evaluate_record(
        rule,
        case.negative,
        observed_domains=case.observed_domains,
        related_records=case.negative_related,
    )
    boundary = service.evaluate_record(
        rule,
        case.boundary,
        observed_domains=case.observed_domains,
        related_records=case.boundary_related,
    )
    missing = service.evaluate_record(
        rule,
        case.positive,
        observed_domains=case.observed_domains[:-1],
        related_records=case.positive_related,
    )

    assert positive.matched is True
    assert negative.matched is False
    assert boundary.matched is False
    assert missing.matched is False
    assert missing.preconditions_met is False
    assert missing.missing_required_domains
    assert positive.protocol_source["source_text"] == case.fact.source_text
    assert positive.protocol_source["source_locator"] == case.fact.source_locator
    assert (
        f"gold:{family}:positive"
        in positive.evidence["current_record"]["source_locators"]
    )


def test_rux_and_my009_real_listing_shapes_drive_fields_without_project_code(
    gold_matrix: dict[str, GoldCase],
) -> None:
    my009_sheets = parse_listing_file(
        MY009_LISTING.name,
        MY009_LISTING.read_bytes(),
    )
    cm = next(sheet for sheet in my009_sheets if sheet.sheet_name == "CM")
    assert {"USUBJID", "CMTRT", "CMSTDAT", "CMENDAT"}.issubset(cm.rows[0])

    cm_rule = _enabled_for_template_evaluation(
        compile_monitoring_rule_template(
            gold_matrix["concomitant_medication_policy"].fact
        )
    )
    cm_result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        cm_rule,
        {
            "USUBJID": "GOLD-MY009-CM",
            "CMTRT": "示例生物制剂",
            "__source_locator__": f"listing:{MY009_LISTING.name}:sheet:CM:row:1",
        },
        observed_domains=["CM"],
    )
    dq_rule = _enabled_for_template_evaluation(
        compile_monitoring_rule_template(gold_matrix["data_quality"].fact)
    )
    dq_result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        dq_rule,
        gold_matrix["data_quality"].positive,
        observed_domains=["LB"],
    )

    # These are gold-standard records shaped from real headers, not conclusions
    # about any actual participant.
    assert cm_result.matched is True
    assert dq_result.matched is True
    assert "CMTRT" in cm_rule.trigger_expression["regex"]["field"]
    assert gold_matrix["data_quality"].fact.source_locator.startswith(
        "listing-mapping:"
    )


def test_gold_templates_use_raw_or_auditable_base_values_not_precomputed_conclusions(
    gold_matrix: dict[str, GoldCase],
) -> None:
    serialized = json.dumps(
        {
            family: {
                "payload": case.fact.normalized_payload,
                "positive": case.positive,
                "negative": case.negative,
                "boundary": case.boundary,
            }
            for family, case in gold_matrix.items()
        },
        ensure_ascii=False,
    )
    assert "_REVIEW_STATUS" not in serialized
    assert "_COMPLETENESS_STATUS" not in serialized
    assert "_CHAIN_STATUS" not in serialized
    assert "_TO_IP_DAYS" not in serialized
    assert "_ADHERENCE_PERCENT" not in serialized
    assert "_WINDOW_DELTA_DAYS" not in serialized
    for case in gold_matrix.values():
        bindings = case.fact.normalized_payload[TEMPLATE_PAYLOAD_KEY][
            "listing_mapping"
        ]["fields"]
        assert not {
            "review_status",
            "interval_days",
            "adherence_percent",
            "window_delta_days",
        }.intersection(bindings)
        for binding in bindings.values():
            lineage = binding["lineage"]
            assert lineage["source_type"] in {
                "raw_listing_field",
                "auditable_base_value",
            }
            assert lineage["source_locator"]
            if lineage["source_type"] == "auditable_base_value":
                assert lineage["input_field_roles"]
                assert lineage["calculation_expression"]
                assert (
                    ("unit_literal" in lineage)
                    != ("unit_field_role" in lineage)
                )
                assert "unit" not in lineage
                assert all(
                    bindings[input_role]["lineage"]["source_type"]
                    == "raw_listing_field"
                    for input_role in lineage["input_field_roles"]
                )


def test_real_rux_and_my009_lineage_uses_file_hash_sheet_and_header_locators(
    gold_matrix: dict[str, GoldCase],
) -> None:
    real_hashes = {
        "proj_rux_03_002": sha256(RUX_LISTING.read_bytes()).hexdigest(),
        "proj_my009_uc": sha256(MY009_LISTING.read_bytes()).hexdigest(),
    }
    for case in gold_matrix.values():
        expected_hash = real_hashes.get(case.fact.project_id)
        if expected_hash is None:
            continue
        bindings = case.fact.normalized_payload[TEMPLATE_PAYLOAD_KEY][
            "listing_mapping"
        ]["fields"]
        for binding in bindings.values():
            lineage = binding["lineage"]
            locator = lineage["source_locator"]
            assert expected_hash in locator
            if lineage["source_type"] != "raw_listing_field":
                assert lineage["input_field_roles"]
                continue
            assert ":sheet:" in locator
            assert ":header:1:field:" in locator


def test_calculation_and_dynamic_match_traces_are_medically_auditable(
    gold_matrix: dict[str, GoldCase],
) -> None:
    service = object.__new__(MonitoringProtocolRuleService)

    interval_case = gold_matrix["study_treatment_change"]
    interval = service.evaluate_record(
        _enabled_for_template_evaluation(
            compile_monitoring_rule_template(interval_case.fact)
        ),
        interval_case.positive,
        observed_domains=interval_case.observed_domains,
    )
    interval_trace = interval.evidence["predicate_trace"]["trigger"]["children"][0]
    assert interval_trace["operator"] == "date_delta_range"
    assert interval_trace["computed_delta_days"] == 5
    assert interval_trace["accepted_range"] == {
        "min_days": 6.0,
        "max_days": 7.0,
    }

    adherence_case = gold_matrix["study_treatment_adherence"]
    adherence = service.evaluate_record(
        _enabled_for_template_evaluation(
            compile_monitoring_rule_template(adherence_case.fact)
        ),
        adherence_case.positive,
        observed_domains=adherence_case.observed_domains,
    )
    ratio_trace = adherence.evidence["predicate_trace"]["trigger"]["children"][1][
        "children"
    ][0]
    assert ratio_trace["operator"] == "ratio_range"
    assert ratio_trace["computed_ratio"] == 70.0
    assert ratio_trace["numerator_value"] == 7
    assert ratio_trace["denominator_value"] == 10

    endpoint_case = gold_matrix["efficacy_endpoint_completeness"]
    endpoint = service.evaluate_record(
        _enabled_for_template_evaluation(
            compile_monitoring_rule_template(endpoint_case.fact)
        ),
        endpoint_case.negative,
        observed_domains=endpoint_case.observed_domains,
        related_records=endpoint_case.negative_related,
    )
    query = endpoint.evidence["missing_record_queries"][0]
    assert query["matching_record_count"] == 1
    assert query["matching_source_locators"] == ["gold:endpoint:negative"]
    assert query["matching_conditions"]["match"][1] == {
        "related_field": "VISIT",
        "operator": "eq",
        "current_field": "VISIT",
        "expected_value": "W8",
    }


def test_dynamic_association_fails_closed_when_current_match_key_is_missing(
    gold_matrix: dict[str, GoldCase],
) -> None:
    case = gold_matrix["ae_sae_aesi_consistency"]
    record = {
        **case.positive,
        "AESEQ": "",
        "__source_locator__": "gold:aesi:missing-current-key",
    }
    result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        _enabled_for_template_evaluation(
            compile_monitoring_rule_template(case.fact)
        ),
        record,
        observed_domains=case.observed_domains,
        related_records={},
    )

    assert result.matched is False
    query = result.evidence["missing_record_queries"][0]
    assert query["query_ready"] is False
    assert query["missing"] is False
    assert query["missing_current_fields"] == ["AESEQ"]


@pytest.mark.parametrize(
    ("family", "record_update"),
    (
        ("study_treatment_change", {"FIRST_IP_DTC": ""}),
        ("visit_window_and_order", {"SVREFDTC": ""}),
        ("study_treatment_adherence", {"ECPLANNUM": 0}),
    ),
)
def test_negated_calculations_do_not_turn_missing_or_invalid_inputs_into_matches(
    family: str,
    record_update: dict[str, Any],
    gold_matrix: dict[str, GoldCase],
) -> None:
    case = gold_matrix[family]
    record = {**case.positive, **record_update}
    result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        _enabled_for_template_evaluation(
            compile_monitoring_rule_template(case.fact)
        ),
        record,
        observed_domains=case.observed_domains,
    )

    assert result.matched is False


def test_rux_real_listing_headers_cover_raw_ae_mh_cs_ncs_and_data_quality_shapes() -> None:
    sheets = parse_listing_file(RUX_LISTING.name, RUX_LISTING.read_bytes())
    by_prefix = {
        prefix: next(sheet for sheet in sheets if sheet.sheet_name.startswith(prefix))
        for prefix in ("AE--", "MH--", "LBCHEM--")
    }
    assert {
        "SUBJID",
        "AETERM",
        "AESTDAT",
    }.issubset(by_prefix["AE--"].rows[0])
    assert {
        "SUBJID",
        "MHTERM",
        "MHSTDAT",
    }.issubset(by_prefix["MH--"].rows[0])
    assert {
        "SUBJID",
        "LBNRIND",
        "LBCLSIGN",
        "LBORRES",
        "LBORRESU",
        "LBORNRLO",
        "LBORNRHI",
    }.issubset(by_prefix["LBCHEM--"].rows[0])


def test_aesi_requires_explicit_confirmed_definition_and_is_not_inferred_elsewhere(
    gold_matrix: dict[str, GoldCase],
) -> None:
    my008 = gold_matrix["ae_sae_aesi_consistency"].fact
    assert compile_monitoring_rule_template(my008).rule_family == (
        "ae_sae_aesi_consistency"
    )
    invalid_template = {
        **my008.normalized_payload[TEMPLATE_PAYLOAD_KEY],
        "aesi_defined": False,
    }
    non_aesi = ProtocolFact.create(
        project_id="proj_non_aesi",
        protocol_version_id=my008.protocol_version_id,
        fact_key="safety.aesi.not_defined",
        fact_type="safety_assessment",
        status="medically_confirmed",
        title="未定义AESI",
        normalized_payload={TEMPLATE_PAYLOAD_KEY: invalid_template},
        source_entry_id="source_non_aesi",
        source_locator="docx:paragraph:1",
        source_text="本方案未定义项目特异性AESI。",
    )
    outcome = try_compile_monitoring_rule_template(non_aesi)
    assert outcome.requires_manual_review is True
    assert outcome.rule is None
    assert "AESI" in outcome.reason


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("unconfirmed_mapping", "medically_confirmed"),
        ("raw_field", "field roles"),
        ("cm_ip_mix", "must not use CM"),
        ("missing_field_role", "unmapped field role"),
    ),
)
def test_template_compiler_fails_closed_on_unsafe_or_incomplete_configuration(
    mutation: str,
    expected: str,
    gold_matrix: dict[str, GoldCase],
) -> None:
    fact = gold_matrix["study_treatment_change"].fact
    template = {
        **fact.normalized_payload[TEMPLATE_PAYLOAD_KEY],
        "listing_mapping": {
            **fact.normalized_payload[TEMPLATE_PAYLOAD_KEY]["listing_mapping"],
            "fields": {
                key: dict(value)
                for key, value in fact.normalized_payload[TEMPLATE_PAYLOAD_KEY][
                    "listing_mapping"
                ]["fields"].items()
            },
        },
    }
    if mutation == "unconfirmed_mapping":
        template["listing_mapping"]["status"] = "candidate"
    elif mutation == "raw_field":
        template["trigger_expression"] = {
            "eq": {"field": "FIRST_IP_DTC", "value": "2025-01-06"}
        }
    elif mutation == "cm_ip_mix":
        template["required_domains"] = ["EX", "CM"]
        template["listing_mapping"]["fields"]["cm_name"] = {
            "field": "CMTRT",
            "domain": "CM",
            "lineage": _fixture_raw_lineage(
                family="study_treatment_change",
                domain="CM",
                field_name="CMTRT",
            ),
        }
    elif mutation == "missing_field_role":
        template["trigger_expression"] = {
            "eq": {"field_role": "unmapped_status", "value": "x"}
        }
    invalid = ProtocolFact.create(
        project_id=fact.project_id,
        protocol_version_id=fact.protocol_version_id,
        fact_key=f"{fact.fact_key}.{mutation}",
        fact_type=fact.fact_type,
        status="medically_confirmed",
        title=fact.title,
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
    )
    with pytest.raises(MonitoringRuleTemplateError, match=expected):
        compile_monitoring_rule_template(invalid)


def test_new_template_rejects_legacy_ambiguous_unit_field(
    gold_matrix: dict[str, GoldCase],
) -> None:
    fact = next(
        case.fact
        for case in gold_matrix.values()
        if any(
            binding["lineage"]["source_type"] == "auditable_base_value"
            for binding in case.fact.normalized_payload[TEMPLATE_PAYLOAD_KEY][
                "listing_mapping"
            ]["fields"].values()
        )
    )
    template = json.loads(
        json.dumps(fact.normalized_payload[TEMPLATE_PAYLOAD_KEY])
    )
    fields = template["listing_mapping"]["fields"]
    derived = next(
        binding["lineage"]
        for binding in fields.values()
        if binding["lineage"]["source_type"] == "auditable_base_value"
    )
    derived["unit"] = derived.pop("unit_literal")
    invalid = ProtocolFact.create(
        project_id=fact.project_id,
        protocol_version_id=fact.protocol_version_id,
        fact_key=f"{fact.fact_key}.legacy_unit",
        fact_type=fact.fact_type,
        status="medically_confirmed",
        title=fact.title,
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
    )
    with pytest.raises(
        MonitoringRuleTemplateError,
        match="exactly one of unit_literal or unit_field_role",
    ):
        compile_monitoring_rule_template(invalid)


def test_current_dsl_explicitly_routes_unexpressible_logic_to_manual_review(
    gold_matrix: dict[str, GoldCase],
) -> None:
    fact = gold_matrix["cross_domain_consistency"].fact
    template = {
        **fact.normalized_payload[TEMPLATE_PAYLOAD_KEY],
        "executor": "manual_review",
    }
    manual_fact = ProtocolFact.create(
        project_id=fact.project_id,
        protocol_version_id=fact.protocol_version_id,
        fact_key=f"{fact.fact_key}.causality",
        fact_type=fact.fact_type,
        status="medically_confirmed",
        title="跨域医学因果链",
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id=fact.source_entry_id,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
    )
    outcome = try_compile_monitoring_rule_template(manual_fact)
    assert outcome.requires_manual_review is True
    assert "manual medical review" in outcome.reason


def test_non_confirmed_fact_never_compiles() -> None:
    fact = ProtocolFact.create(
        project_id="proj_candidate",
        protocol_version_id="protov_candidate",
        fact_key="safety.candidate",
        fact_type="safety_assessment",
        status="ai_candidate",
        title="AI候选事实",
        normalized_payload={TEMPLATE_PAYLOAD_KEY: {}},
        source_entry_id="source_candidate",
        source_locator="docx:paragraph:1",
        source_text="候选原文。",
    )
    with pytest.raises(MonitoringRuleTemplateError, match="medically_confirmed"):
        compile_monitoring_rule_template(fact)


def _identity_template() -> dict[str, Any]:
    return _symbolic_template(
        family="data_quality",
        rule_key="visit_data_completeness_identity",
        executor="field_predicate",
        required_domains=("LB",),
        fields={"review_flag": ("REVIEW_FLAG", "LB")},
        trigger={"eq": {"field_role": "review_flag", "value": "CHECK"}},
        title="访视数据完整性核对",
    )


def _identity_fact(template: dict[str, Any]) -> ProtocolFact:
    return ProtocolFact.create(
        project_id="proj_identity",
        protocol_version_id="protov_identity",
        fact_key="data_quality.identity",
        fact_type="data_quality",
        status="medically_confirmed",
        title="访视数据完整性核对",
        normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
        source_entry_id="source_identity",
        source_locator="docx:paragraph:1",
        source_text="受试者每次访视均应完成数据完整性核对。",
    )


def test_compiler_propagates_immutable_identity_into_candidate_rule() -> None:
    identity = {
        "mapping_revision": "mapping-revision-001",
        "mapping_content_sha256": "a" * 64,
        "capability_manifest_sha256": "b" * 64,
        "effective_capabilities_sha256": "c" * 64,
        "recommendation_candidate_id": "candidate-001",
    }
    legacy = compile_monitoring_rule_template(_identity_fact(_identity_template()))
    assert legacy.status == "candidate"
    assert legacy.mapping_revision == ""
    assert legacy.mapping_content_sha256 == ""
    assert legacy.title == "访视数据完整性核对（需医学复核候选）"

    template = _identity_template()
    template["immutable_identity"] = identity
    rule = compile_monitoring_rule_template(_identity_fact(template))
    assert rule.status == "candidate"
    assert rule.mapping_revision == "mapping-revision-001"
    assert rule.mapping_content_sha256 == "a" * 64
    assert rule.capability_manifest_sha256 == "b" * 64
    assert rule.effective_capabilities_sha256 == "c" * 64
    assert rule.recommendation_candidate_id == "candidate-001"
    assert rule.rule_revision_id != legacy.rule_revision_id
    # Adoption through the recommendation chain is already the medical
    # decision: the compiled rule title must not keep candidate wording.
    assert rule.title == "访视数据完整性核对"


def test_compiler_fails_closed_on_incomplete_immutable_identity() -> None:
    template = _identity_template()
    template["immutable_identity"] = {
        "mapping_revision": "mapping-revision-001",
        "mapping_content_sha256": "a" * 64,
    }
    with pytest.raises(
        MonitoringRuleTemplateError,
        match="immutable_identity is incomplete",
    ):
        compile_monitoring_rule_template(_identity_fact(template))

    non_mapping = _identity_template()
    non_mapping["immutable_identity"] = "mapping-revision-001"
    with pytest.raises(
        MonitoringRuleTemplateError,
        match="immutable_identity must be an object",
    ):
        compile_monitoring_rule_template(_identity_fact(non_mapping))
