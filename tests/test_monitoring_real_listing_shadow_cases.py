"""Real-listing cases for rule candidates, never subject-level medical conclusions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

import pytest

from packages.contracts.workbench_contracts import (
    SourceRegistrationResult,
    SourceRegistryEntry,
)

from services.api.app.listing_file_parser import (
    LISTING_PARSER_VERSION,
    parse_listing_file,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_gold_case_authority import (
    MonitoringGoldCaseAuthority,
    monitoring_batch_revision,
    monitoring_source_revision,
)
from services.api.app.monitoring_protocol_rules import (
    MonitoringRuleDefinition,
    ProtocolFact,
    ProtocolSourceVersion,
    RuleGoldRecordFieldBinding,
    RuleGoldSourceRowBinding,
    RuleGoldStandardCase,
    RuleSourceReference,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    RulePackLifecycleError,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_source_fragment import (
    resolve_protocol_fragment,
)
from services.api.app.protocol_text_extractor import parse_protocol_docx


RUX_LISTING = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
MY009_LISTING = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
RUX_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
    "RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/"
    "V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
MY009_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)

LISTING_SPECS = {
    "rux": {
        "path": RUX_LISTING,
        "sha256": "b68d53feb7cd4501d5fae876a0053db2843597eed216b76203c2c9ea6daea343",
    },
    "my009": {
        "path": MY009_LISTING,
        "sha256": "c3dfa3933e76788a2f586f05eb921f117ed0a5fd00f926591b1fbdb888f2d7e0",
    },
}
PROTOCOL_SPECS = {
    "rux": {
        "path": RUX_PROTOCOL,
        "sha256": "8783a740fc0595491f059b8753342f1819e746d80dc390317302ae30b5de5b62",
        "project_id": "proj_rux_03_002",
        "protocol_code": "RUX-03-002",
        "version_label": "V1.3",
        "version_date": "2024-08-14",
    },
    "my009": {
        "path": MY009_PROTOCOL,
        "sha256": "d173e4b05d5856f62affd21abb28345d71b6ef61f2c322f8f9454ff9e19b75ae",
        "project_id": "proj_my009_uc",
        "protocol_code": "MY009-UC-2-01",
        "version_label": "V3.0",
        "version_date": "2025-09-26",
    },
}

PROTOCOL_EXCERPT_SPECS = {
    "rux_ae_boundary": (
        "rux",
        "docx:paragraph:1285",
        "此外，自签署知情同意书后至首次用药之前，发生的临床不良事件作为病史/"
        "伴随疾病记录在CRF中，不作为AE记录，除非符合后述情况之一：任何临床实验室"
        "检查操作造成的伤害/损害；与试验方案相关的停药引起的不良事件；作为治疗方案"
        "的一部分而服用的试验用药品以外的药物所引起的不良事件。",
    ),
    "my009_lab_significance": (
        "my009",
        "docx:paragraph:1351",
        "研究者需清晰的标记超出范围的实验室结果并指出是否具有临床意义。对于达到"
        "CTCAE 2级及以上的实验室检查异常，如果研究者评估为NCS，应提供异常合理原因。",
    ),
    "my009_allowed_steroid": (
        "my009",
        "docx:paragraph:1108",
        "V2访视前口服5-ASA、小剂量皮质类固醇（泼尼松≤20 mg/天或等效类固醇）、"
        "布地奈德MMX（≤9 mg/天）、药用益生菌稳定剂量使用≥14天的患者，允许研究期间"
        "继续稳定剂量持续服用。对于筛选时尚未服用这些药物的受试者，不应在研究期间"
        "起始这些药物。\n6.5.2禁止使用的合并用药：",
    ),
    "my009_prohibited_biologic": (
        "my009",
        "docx:paragraph:1110",
        "生物制剂及新型小分子化药（包括但不局限于JAK抑制剂、S1PR调节剂等）："
        "本研究期间禁止使用；",
    ),
    "rux_visit_days": (
        "rux",
        "docx:table:2:row:2",
        "访视天；D-28~D-1；D15；D29；D57；D85；D113；D141；D169；D197",
    ),
    "rux_visit_windows": (
        "rux",
        "docx:table:2:row:3",
        "访视窗口期\n(±日历天数)；± 3d；± 3d；± 3d；± 7d；± 7d；"
        "± 7d；± 7d；+ 7d",
    ),
    "rux_adherence": (
        "rux",
        "docx:paragraph:1014",
        "用药依从性将由实际使用次数与预期使用次数决定，除非申办者另有讨论/批准，"
        "否则双盲治疗期使用次数应在规定使用次数的80%-120%内。须告知受试者在研究"
        "访视时携带所有发放的已使用和未使用的研究药物，以便中心人员进行研究药物计数。",
    ),
    "my009_ae_boundary": (
        "my009",
        "docx:paragraph:1356",
        "受试者签署知情同意书后至开始服用导入期试验用药物之前，发生的临床不良医学"
        "事件作为病史/伴随疾病记录，不作为AE记录。",
    ),
}

DETERMINATE_CASE_IDS = (
    "AE-01",
    "AE-02",
    "LB-01",
    "LB-02",
    "LB-03",
    "LB-04",
    "CM-01",
    "CM-02",
    "SV-01",
    "SV-02",
    "ADH-01",
    "ADH-02",
    "DQ-01",
)
FORBIDDEN_PLACEHOLDER_FIELDS = (
    "FIRSTDOSEDAT",
    "C5_TO_IP_DAYS",
    "ECACTNUM",
    "ECPLANNUM",
    "REVIEW_STATUS",
)

_REAL_RULE_FACT_TYPES: Mapping[str, tuple[str, ...]] = {
    "ae_mh.pre_treatment_event_without_same_day_history": (
        "safety_assessment",
    ),
    "lab.out_of_range_missing_or_normal_significance": (
        "safety_assessment",
    ),
    "cm.allowed_steroid_dose_or_stability": (
        "concomitant_medication_allowed",
    ),
    "cm.prohibited_biologic_overlaps_treatment": (
        "concomitant_medication_prohibited",
    ),
    "visit.actual_date_outside_inclusive_window": (
        "visit_schedule",
        "visit_window",
    ),
    "study_treatment.adherence_outside_80_120": (
        "study_treatment_adherence",
    ),
    "data_quality.reported_adherence_arithmetic": ("data_quality",),
}


@dataclass(frozen=True)
class LocatedRow:
    source_key: str
    sheet_name: str
    excel_row: int
    values: Mapping[str, str]
    locator: str


@dataclass(frozen=True)
class RawCheck:
    row: LocatedRow
    expected_values: Mapping[str, str]


@dataclass(frozen=True)
class ProtocolExcerpt:
    key: str
    source_key: str
    source_entry_id: str
    source_locator: str
    source_text: str
    fact_revision_id: str


@dataclass(frozen=True)
class RealListingCase:
    case_id: str
    classification: str
    expected_match: bool | None
    rule: MonitoringRuleDefinition
    current_record: Mapping[str, Any]
    observed_domains: tuple[str, ...]
    related_records: Mapping[str, Sequence[Mapping[str, Any]]]
    raw_checks: tuple[RawCheck, ...]
    rows: Mapping[str, LocatedRow]
    expected_current_locators: tuple[str, ...]
    expected_related_locators: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class _RegistryReader:
    results: tuple[SourceRegistrationResult, ...]

    def list_results(self, project_id: str) -> list[SourceRegistrationResult]:
        return [
            result
            for result in self.results
            if result.entry.project_id == project_id
        ]


def _located_row(
    listings: Mapping[str, Mapping[str, Any]],
    source_key: str,
    sheet_name: str,
    excel_row: int,
) -> LocatedRow:
    source = listings[source_key]
    sheet = source["sheets"][sheet_name]
    rows_by_number = dict(zip(sheet.row_numbers, sheet.rows))
    assert excel_row in rows_by_number, (
        f"source drift: {source_key}/{sheet_name} has no Excel row {excel_row}"
    )
    return LocatedRow(
        source_key=source_key,
        sheet_name=sheet_name,
        excel_row=excel_row,
        values=rows_by_number[excel_row],
        locator=(
            f"listing:{source['sha256']}:sheet:{sheet_name}:row:{excel_row}"
        ),
    )


def _subject_rows(
    listings: Mapping[str, Mapping[str, Any]],
    source_key: str,
    sheet_name: str,
    subject_field: str,
    subject_id: str,
) -> tuple[LocatedRow, ...]:
    source = listings[source_key]
    sheet = source["sheets"][sheet_name]
    return tuple(
        LocatedRow(
            source_key=source_key,
            sheet_name=sheet_name,
            excel_row=row_number,
            values=row,
            locator=(
                f"listing:{source['sha256']}:sheet:{sheet_name}:row:{row_number}"
            ),
        )
        for row_number, row in zip(sheet.row_numbers, sheet.rows)
        if row.get(subject_field) == subject_id
    )


def _evidence_row(row: LocatedRow) -> dict[str, Any]:
    return {**row.values, "__source_locator__": row.locator}


def _raw_check(row: LocatedRow, **expected_values: str) -> RawCheck:
    return RawCheck(row=row, expected_values=expected_values)


def _protocol_rule(
    *,
    version: ProtocolSourceVersion,
    excerpts: Sequence[ProtocolExcerpt],
    rule_key: str,
    rule_family: str,
    title: str,
    executor: str,
    required_domains: Sequence[str],
    trigger_expression: Mapping[str, Any],
    clinical_domain: str = "",
    field_lineage: Mapping[str, Any] | None = None,
) -> MonitoringRuleDefinition:
    refs = sorted(
        (
            RuleSourceReference.create(
                fact_revision_id=excerpt.fact_revision_id,
                source_entry_id=excerpt.source_entry_id,
                source_locator=excerpt.source_locator,
                source_text=excerpt.source_text,
            )
            for excerpt in excerpts
        ),
        key=lambda item: item.fact_revision_id,
    )
    primary = refs[0]
    source_key = next(
        key
        for key, spec in PROTOCOL_SPECS.items()
        if spec["project_id"] == version.project_id
    )
    listing_sha256 = LISTING_SPECS[source_key]["sha256"]
    used_fields = {"USUBJID"}

    def collect_fields(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in {
                    "field",
                    "other_field",
                    "numerator_field",
                    "denominator_field",
                    "related_field",
                    "current_field",
                    "related_date_field",
                    "current_date_field",
                }:
                    used_fields.add(str(item))
                else:
                    collect_fields(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect_fields(item)

    collect_fields(trigger_expression)
    field_domains = {
        "AESTDAT": "AE",
        "AETERM": "AE",
        "ECADAT": "EC",
        "FIRST_ECADAT": "EC",
        "SUBJID": "MH",
        "MHTERM": "MH",
        "MHSTDAT": "MH",
        "LBORRESN_MINUS_LBORNRLO": "LB",
        "LBORRESN_MINUS_LBORNRHI": "LB",
        "LBORRESN": "LB",
        "LBORNRLO": "LB",
        "LBORNRHI": "LB",
        "LBORRESU": "LB",
        "LBSIG": "LB",
        "CM1TRT": "CM",
        "CM1DOSE": "CM",
        "CM1STDAT": "CM",
        "CM1TRT__13": "CM",
        "CM1ENDAT": "CM",
        "VISDAT": "SV",
        "SVDAT": "SV",
        "SVDATPE": "SV",
        "SVDATPL": "SV",
        "DAADOFRQ": "DA",
        "DAPDOFRQ": "DA",
        "DAB_ABS_PERCENTAGE_POINT_DELTA": "DA",
        "EXDAT": "EX",
        "USUBJID": required_domains[0],
    }

    def role_token(prefix: str, field_name: str) -> str:
        normalized = re.sub(r"[^a-z0-9_]+", "_", field_name.lower()).strip("_")
        return f"{prefix}_{normalized}"

    canonical_lineage: dict[str, dict[str, Any]] = {}
    legacy_overrides = dict(field_lineage or {})
    calculation_by_field = {
        "FIRST_ECADAT": "minimum(ecadat_raw)",
        "LBORRESN_MINUS_LBORNRLO": "lborresn_raw - lbornrlo_raw",
        "LBORRESN_MINUS_LBORNRHI": "lborresn_raw - lbornrhi_raw",
        "DAB_ABS_PERCENTAGE_POINT_DELTA": (
            "abs(dabmeco_raw - daadofrq_raw / dapdofrq_raw * 100)"
        ),
        "EXDAT": "minimum(exdat_raw)",
    }
    for field_name in sorted(used_fields):
        domain = field_domains.get(field_name, required_domains[0])
        override = legacy_overrides.get(field_name)
        if override is None:
            role = role_token("raw", field_name)
            canonical_lineage[role] = {
                "field": field_name,
                "domain": domain,
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        f"listing:{listing_sha256}:sheet:{domain}:"
                        f"header:1:field:{field_name}"
                    ),
                },
            }
            continue
        raw_fields = [
            str(item).split(".")[-1]
            for item in override.get("input_fields", ())
        ]
        if not raw_fields:
            raw_fields = [field_name]
        raw_roles: list[str] = []
        for raw_field in raw_fields:
            raw_role = role_token("raw", raw_field)
            if raw_role not in canonical_lineage:
                canonical_lineage[raw_role] = {
                    "field": raw_field,
                    "domain": field_domains.get(raw_field, domain),
                    "lineage": {
                        "source_type": "raw_listing_field",
                        "source_locator": (
                            f"listing:{listing_sha256}:sheet:"
                            f"{field_domains.get(raw_field, domain)}:"
                            f"header:1:field:{raw_field}"
                        ),
                    },
                }
            raw_roles.append(raw_role)
        expression = calculation_by_field[field_name]
        unit_field = str(override.get("unit_field") or "")
        unit_literal = str(override.get("unit_literal") or "")
        assert bool(unit_field) != bool(unit_literal)
        if unit_field and unit_field not in raw_fields:
            raw_field = unit_field
            raw_role = role_token("raw", raw_field)
            canonical_lineage[raw_role] = {
                "field": raw_field,
                "domain": field_domains.get(raw_field, domain),
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": (
                        f"listing:{listing_sha256}:sheet:"
                        f"{field_domains.get(raw_field, domain)}:"
                        f"header:1:field:{raw_field}"
                    ),
                },
            }
            raw_roles.append(raw_role)
        calculation = expression
        for raw_role in raw_roles:
            raw_field = canonical_lineage[raw_role]["field"].lower()
            calculation = re.sub(
                rf"\b{re.escape(raw_field)}_raw\b",
                raw_role,
                calculation,
            )
        derived_role = role_token("derived", field_name)
        calculation_input_roles = tuple(
            role
            for role in raw_roles
            if re.search(rf"\b{re.escape(role)}\b", calculation)
        )
        input_roles = list(calculation_input_roles)
        unit_contract: dict[str, str]
        if unit_field:
            unit_role = role_token("raw", unit_field)
            if unit_role not in input_roles:
                input_roles.append(unit_role)
            unit_contract = {"unit_field_role": unit_role}
        else:
            unit_contract = {"unit_literal": unit_literal}
        canonical_lineage[derived_role] = {
            "field": field_name,
            "domain": domain,
            "lineage": {
                "source_type": "auditable_base_value",
                "input_field_roles": input_roles,
                "calculation_expression": calculation,
                **unit_contract,
                "source_locator": (
                    f"listing:{listing_sha256}:derived:field:{field_name}:"
                    "header-source"
                ),
            },
        }
    return MonitoringRuleDefinition.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rule_key=rule_key,
        rule_family=rule_family,
        status="enabled",
        title=title,
        executor=executor,
        required_domains=required_domains,
        preconditions={"exists": {"field": "USUBJID"}},
        trigger_expression=trigger_expression,
        exclusions={"missing": {"field": "USUBJID"}},
        severity="high",
        confidence="deterministic",
        evidence_template=(
            "{USUBJID}：确定性规则触发，仅形成医学复核候选，不构成医学结论。"
        ),
        fact_revision_ids=[ref.fact_revision_id for ref in refs],
        source_entry_id=primary.source_entry_id,
        source_locator=primary.source_locator,
        source_text=primary.source_text,
        clinical_domain=clinical_domain,
        source_refs=refs,
        field_lineage=canonical_lineage,
    )


@pytest.fixture(scope="module")
def listing_sources() -> dict[str, dict[str, Any]]:
    assert LISTING_PARSER_VERSION == "listing_file_parser_v3_ooxml_metadata_recovery"
    result: dict[str, dict[str, Any]] = {}
    for source_key, spec in LISTING_SPECS.items():
        content = spec["path"].read_bytes()
        actual_sha256 = sha256(content).hexdigest()
        assert actual_sha256 == spec["sha256"], (
            f"source drift: {source_key} listing SHA-256 is {actual_sha256}"
        )
        parsed_sheets = parse_listing_file(spec["path"].name, content)
        result[source_key] = {
            "sha256": actual_sha256,
            "sheets": {sheet.sheet_name: sheet for sheet in parsed_sheets},
        }
    return result


@pytest.fixture(scope="module")
def protocol_bundle() -> dict[str, Any]:
    documents = {}
    versions = {}
    for source_key, spec in PROTOCOL_SPECS.items():
        content = spec["path"].read_bytes()
        actual_sha256 = sha256(content).hexdigest()
        assert actual_sha256 == spec["sha256"], (
            f"source drift: {source_key} protocol SHA-256 is {actual_sha256}"
        )
        documents[source_key] = parse_protocol_docx(spec["path"].name, content)
        versions[source_key] = ProtocolSourceVersion.create(
            project_id=spec["project_id"],
            protocol_code=spec["protocol_code"],
            version_label=spec["version_label"],
            version_date=spec["version_date"],
            source_entry_id=f"source_{source_key}_protocol",
            source_title=spec["path"].name,
            content_sha256=actual_sha256,
        )

    excerpts = {}
    for key, (source_key, locator, expected_text) in PROTOCOL_EXCERPT_SPECS.items():
        fragment = resolve_protocol_fragment(documents[source_key], locator)
        assert fragment["text"] == expected_text, (
            f"protocol source drift at {source_key}/{locator}"
        )
        excerpts[key] = ProtocolExcerpt(
            key=key,
            source_key=source_key,
            source_entry_id=f"source_{source_key}_protocol",
            source_locator=locator,
            source_text=fragment["text"],
            fact_revision_id=(
                "protfact_"
                + sha256(
                    f"{source_key}|{locator}|{fragment['text']}".encode("utf-8")
                ).hexdigest()[:24]
            ),
        )

    rules = {
        "rux_ae_boundary": _protocol_rule(
            version=versions["rux"],
            excerpts=[excerpts["rux_ae_boundary"]],
            rule_key="ae_mh.pre_treatment_event_without_same_day_history",
            rule_family="ae_mh_missing_review",
            title="首次实际用药前AE且无同日同词MH记录",
            executor="cross_record",
            required_domains=("AE", "EC", "MH"),
            trigger_expression={
                "all": [
                    {
                        "date_compare": {
                            "field": "AESTDAT",
                            "other_field": "FIRST_ECADAT",
                            "relation": "before",
                        }
                    },
                    {
                        "no_corresponding_record": {
                            "domain": "MH",
                            "match": [
                                {
                                    "related_field": "SUBJID",
                                    "current_field": "USUBJID",
                                },
                                {
                                    "related_field": "MHTERM",
                                    "current_field": "AETERM",
                                },
                            ],
                            "date_window": {
                                "related_date_field": "MHSTDAT",
                                "current_date_field": "AESTDAT",
                                "min_days": 0,
                                "max_days": 0,
                            },
                        }
                    },
                ]
            },
            field_lineage={
                "FIRST_ECADAT": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["ECADAT"],
                    "calculation_expression": (
                        "minimum(ECADAT) among complete EC rows for current SUBJID"
                    ),
                    "unit_literal": "ISO-8601 date",
                }
            },
        ),
        "my009_lab_significance": _protocol_rule(
            version=versions["my009"],
            excerpts=[excerpts["my009_lab_significance"]],
            rule_key="lab.out_of_range_missing_or_normal_significance",
            rule_family="cs_ncs_review",
            title="实验室超范围且临床意义缺失或评价为正常",
            executor="field_predicate",
            required_domains=("LB",),
            trigger_expression={
                "all": [
                    {
                        "any": [
                            {
                                "lt": {
                                    "field": "LBORRESN_MINUS_LBORNRLO",
                                    "value": 0,
                                }
                            },
                            {
                                "gt": {
                                    "field": "LBORRESN_MINUS_LBORNRHI",
                                    "value": 0,
                                }
                            },
                        ]
                    },
                    {
                        "any": [
                            {"missing": {"field": "LBSIG"}},
                            {"eq": {"field": "LBSIG", "value": "正常"}},
                        ]
                    },
                ]
            },
            field_lineage={
                "LBORRESN_MINUS_LBORNRLO": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["LBORRESN", "LBORNRLO"],
                    "calculation_expression": (
                        "decimal(LBORRESN) - decimal_bound(LBORNRLO)"
                    ),
                    "unit_field": "LBORRESU",
                },
                "LBORRESN_MINUS_LBORNRHI": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["LBORRESN", "LBORNRHI"],
                    "calculation_expression": (
                        "decimal(LBORRESN) - decimal_bound(LBORNRHI)"
                    ),
                    "unit_field": "LBORRESU",
                },
            },
        ),
        "my009_allowed_steroid": _protocol_rule(
            version=versions["my009"],
            excerpts=[excerpts["my009_allowed_steroid"]],
            rule_key="cm.allowed_steroid_dose_or_stability",
            rule_family="concomitant_medication_policy",
            title="允许口服激素剂量或稳定期不满足",
            executor="temporal",
            required_domains=("CM", "SV"),
            trigger_expression={
                "all": [
                    {
                        "regex": {
                            "field": "CM1TRT",
                            "value": "泼尼松",
                        }
                    },
                    {
                        "any": [
                            {"gt": {"field": "CM1DOSE", "value": 20}},
                            {
                                "not": {
                                    "date_delta_range": {
                                        "field": "VISDAT",
                                        "other_field": "CM1STDAT",
                                        "min_days": 14,
                                    }
                                }
                            },
                        ]
                    },
                ]
            },
        ),
        "my009_prohibited_biologic": _protocol_rule(
            version=versions["my009"],
            excerpts=[excerpts["my009_prohibited_biologic"]],
            rule_key="cm.prohibited_biologic_overlaps_treatment",
            rule_family="concomitant_medication_policy",
            title="生物制剂使用期与导入期重叠",
            executor="temporal",
            required_domains=("CM", "SV"),
            trigger_expression={
                "all": [
                    {
                        "eq": {
                            "field": "CM1TRT__13",
                            "value": "单克隆抗体",
                        }
                    },
                    {
                        "date_compare": {
                            "field": "CM1ENDAT",
                            "other_field": "VISDAT",
                            "relation": "after_or_equal",
                        }
                    },
                ]
            },
        ),
        "rux_visit_window": _protocol_rule(
            version=versions["rux"],
            excerpts=[
                excerpts["rux_visit_days"],
                excerpts["rux_visit_windows"],
            ],
            rule_key="visit.actual_date_outside_inclusive_window",
            rule_family="visit_window_and_order",
            title="实际访视日期超出含端点窗口",
            executor="temporal",
            required_domains=("SV",),
            trigger_expression={
                "any": [
                    {
                        "date_compare": {
                            "field": "SVDAT",
                            "other_field": "SVDATPE",
                            "relation": "before",
                        }
                    },
                    {
                        "date_compare": {
                            "field": "SVDAT",
                            "other_field": "SVDATPL",
                            "relation": "after",
                        }
                    },
                ]
            },
        ),
        "rux_adherence": _protocol_rule(
            version=versions["rux"],
            excerpts=[excerpts["rux_adherence"]],
            rule_key="study_treatment.adherence_outside_80_120",
            rule_family="study_treatment_adherence",
            title="实际使用次数与预期使用次数比例超出80%-120%",
            executor="field_predicate",
            required_domains=("DA",),
            trigger_expression={
                "not": {
                    "ratio_range": {
                        "numerator_field": "DAADOFRQ",
                        "denominator_field": "DAPDOFRQ",
                        "multiplier": 100,
                        "min_value": 80,
                        "max_value": 120,
                    }
                }
            },
        ),
        "rux_adherence_arithmetic": _protocol_rule(
            version=versions["rux"],
            excerpts=[excerpts["rux_adherence"]],
            rule_key="data_quality.reported_adherence_arithmetic",
            rule_family="data_quality",
            title="系统依从性与原始次数算术不一致",
            executor="field_predicate",
            required_domains=("DA",),
            clinical_domain="data_quality",
            trigger_expression={
                "gt": {
                    "field": "DAB_ABS_PERCENTAGE_POINT_DELTA",
                    "value": 0,
                }
            },
            field_lineage={
                "DAB_ABS_PERCENTAGE_POINT_DELTA": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["DAADOFRQ", "DAPDOFRQ", "DABMECO"],
                    "calculation_expression": (
                        "abs(decimal(DABMECO) - "
                        "decimal(DAADOFRQ) / decimal(DAPDOFRQ) * 100)"
                    ),
                    "unit_literal": "percentage points",
                }
            },
        ),
        "my009_induction_ae_boundary": _protocol_rule(
            version=versions["my009"],
            excerpts=[excerpts["my009_ae_boundary"]],
            rule_key="ae.induction_actual_use_boundary",
            rule_family="cross_domain_consistency",
            title="导入期首次实际服药前事件归类边界",
            executor="cross_record",
            required_domains=("AE", "EX", "DA", "SV"),
            clinical_domain="safety",
            trigger_expression={
                "date_compare": {
                    "field": "AESTDAT",
                    "other_field": "EXDAT",
                    "relation": "before",
                }
            },
            field_lineage={
                "EXDAT": {
                    "source_type": "raw_listing_field",
                    "input_fields": ["EX.EXDAT", "EX.VISIT", "EX.USUBJID"],
                    "selection_expression": (
                        "earliest actual EXDAT in the induction-period EX search set"
                    ),
                    "unit_literal": "ISO-8601 date",
                }
            },
        ),
    }
    return {
        "documents": documents,
        "versions": versions,
        "excerpts": excerpts,
        "rules": rules,
    }


def _decimal_bound(value: str) -> Decimal:
    match = re.fullmatch(r"\s*(?:<=|>=|<|>)?\s*(-?\d+(?:\.\d+)?)\s*", value)
    assert match, f"unparseable numeric reference bound: {value!r}"
    return Decimal(match.group(1))


def _lab_record(row: LocatedRow) -> dict[str, Any]:
    result = Decimal(row.values["LBORRESN"])
    lower = _decimal_bound(row.values["LBORNRLO"])
    upper = _decimal_bound(row.values["LBORNRHI"])
    lower_delta = result - lower
    upper_delta = result - upper
    return {
        "USUBJID": row.values["USUBJID"],
        "LBTEST": row.values["LBTEST"],
        "LBORRES": row.values["LBORRES"],
        "LBORRESN": row.values["LBORRESN"],
        "LBORRESU": row.values["LBORRESU"],
        "LBORNRLO": row.values["LBORNRLO"],
        "LBORNRHI": row.values["LBORNRHI"],
        "LBSIG": row.values.get("LBSIG", ""),
        "LBORRESN_MINUS_LBORNRLO": str(lower_delta),
        "LBORRESN_MINUS_LBORNRHI": str(upper_delta),
        "__source_locator__": row.locator,
        "__auditable_base_values__": {
            "LBORRESN_MINUS_LBORNRLO": {
                "source_type": "auditable_base_value",
                "input_fields": ["LBORRESN", "LBORNRLO"],
                "input_locators": [row.locator],
                "calculation_expression": (
                    "decimal(LBORRESN) - decimal_bound(LBORNRLO)"
                ),
                "unit": row.values["LBORRESU"],
                "calculated_value": str(lower_delta),
            },
            "LBORRESN_MINUS_LBORNRHI": {
                "source_type": "auditable_base_value",
                "input_fields": ["LBORRESN", "LBORNRHI"],
                "input_locators": [row.locator],
                "calculation_expression": (
                    "decimal(LBORRESN) - decimal_bound(LBORNRHI)"
                ),
                "unit": row.values["LBORRESU"],
                "calculated_value": str(upper_delta),
            },
        },
    }


@pytest.fixture(scope="module")
def real_cases(
    listing_sources: Mapping[str, Mapping[str, Any]],
    protocol_bundle: Mapping[str, Any],
) -> dict[str, RealListingCase]:
    rules = protocol_bundle["rules"]
    cases: dict[str, RealListingCase] = {}

    rux_ae_sheet = "AE--不良事件"
    rux_eca_sheet = "ECA--研究药物给药-实际用药"
    rux_mh_sheet = "MH--既往及现病史"
    rux_sv_sheet = "SV--访视日期"
    rux_dab_sheet = "DAB--研究药物回收"

    ae_01 = _located_row(listing_sources, "rux", rux_ae_sheet, 66)
    ae_01_ec_rows = _subject_rows(
        listing_sources, "rux", rux_eca_sheet, "SUBJID", "S01020"
    )
    ae_01_mh_rows = _subject_rows(
        listing_sources, "rux", rux_mh_sheet, "SUBJID", "S01020"
    )
    ae_01_first_ec = min(ae_01_ec_rows, key=lambda row: row.values["ECADAT"])
    ae_01_record = {
        "USUBJID": ae_01.values["SUBJID"],
        "AETERM": ae_01.values["AETERM"],
        "AESTDAT": ae_01.values["AESTDAT"],
        "FIRST_ECADAT": ae_01_first_ec.values["ECADAT"],
        "__source_locator__": [ae_01.locator, ae_01_first_ec.locator],
        "__auditable_base_values__": {
            "FIRST_ECADAT": {
                "source_type": "auditable_base_value",
                "input_fields": ["ECADAT"],
                "input_locators": [row.locator for row in ae_01_ec_rows],
                "calculation_expression": (
                    "minimum(ECADAT) among complete EC rows for current SUBJID"
                ),
                "unit": "ISO-8601 date",
                "calculated_value": ae_01_first_ec.values["ECADAT"],
            }
        },
    }
    cases["AE-01"] = RealListingCase(
        case_id="AE-01",
        classification="real_positive",
        expected_match=True,
        rule=rules["rux_ae_boundary"],
        current_record=ae_01_record,
        observed_domains=("AE", "EC", "MH"),
        related_records={
            "EC": [_evidence_row(row) for row in ae_01_ec_rows],
            "MH": [_evidence_row(row) for row in ae_01_mh_rows],
        },
        raw_checks=(
            _raw_check(
                ae_01,
                SUBJID="S01020",
                AETERM="皮肤瘙痒",
                AESTDAT="2024-08-26",
            ),
            _raw_check(
                ae_01_first_ec,
                SUBJID="S01020",
                ECADAT="2024-09-02",
            ),
            *tuple(
                _raw_check(row, SUBJID="S01020", MHTERM=term)
                for row, term in zip(
                    ae_01_mh_rows,
                    ("痤疮", "眼睑皮炎", "干眼症", "荨麻疹", "尿蛋白阳性"),
                )
            ),
        ),
        rows={"ae": ae_01, "first_ec": ae_01_first_ec},
        expected_current_locators=(ae_01.locator, ae_01_first_ec.locator),
        expected_related_locators={
            "EC": tuple(row.locator for row in ae_01_ec_rows),
            "MH": tuple(row.locator for row in ae_01_mh_rows),
        },
    )

    ae_02 = _located_row(listing_sources, "rux", rux_ae_sheet, 36)
    ae_02_ec_rows = _subject_rows(
        listing_sources, "rux", rux_eca_sheet, "SUBJID", "S01009"
    )
    ae_02_mh_rows = _subject_rows(
        listing_sources, "rux", rux_mh_sheet, "SUBJID", "S01009"
    )
    ae_02_first_ec = min(ae_02_ec_rows, key=lambda row: row.values["ECADAT"])
    ae_02_mh_term = next(
        row for row in ae_02_mh_rows if row.values["MHTERM"] == "毛囊炎"
    )
    ae_02_record = {
        "USUBJID": ae_02.values["SUBJID"],
        "AETERM": ae_02.values["AETERM"],
        "AESTDAT": ae_02.values["AESTDAT"],
        "FIRST_ECADAT": ae_02_first_ec.values["ECADAT"],
        "__source_locator__": [ae_02.locator, ae_02_first_ec.locator],
        "__auditable_base_values__": {
            "FIRST_ECADAT": {
                "source_type": "auditable_base_value",
                "input_fields": ["ECADAT"],
                "input_locators": [row.locator for row in ae_02_ec_rows],
                "calculation_expression": (
                    "minimum(ECADAT) among complete EC rows for current SUBJID"
                ),
                "unit": "ISO-8601 date",
                "calculated_value": ae_02_first_ec.values["ECADAT"],
            }
        },
    }
    cases["AE-02"] = RealListingCase(
        case_id="AE-02",
        classification="real_negative",
        expected_match=False,
        rule=rules["rux_ae_boundary"],
        current_record=ae_02_record,
        observed_domains=("AE", "EC", "MH"),
        related_records={
            "EC": [_evidence_row(row) for row in ae_02_ec_rows],
            "MH": [_evidence_row(row) for row in ae_02_mh_rows],
        },
        raw_checks=(
            _raw_check(
                ae_02,
                SUBJID="S01009",
                AETERM="毛囊炎",
                AESTDAT="2024-12-07",
            ),
            _raw_check(
                ae_02_first_ec,
                SUBJID="S01009",
                ECADAT="2024-07-17",
            ),
            _raw_check(
                ae_02_mh_term,
                SUBJID="S01009",
                MHTERM="毛囊炎",
                MHSTDAT="2023-03-03",
            ),
        ),
        rows={
            "ae": ae_02,
            "first_ec": ae_02_first_ec,
            "same_term_mh": ae_02_mh_term,
        },
        expected_current_locators=(ae_02.locator, ae_02_first_ec.locator),
        expected_related_locators={
            "EC": tuple(row.locator for row in ae_02_ec_rows),
            "MH": tuple(row.locator for row in ae_02_mh_rows),
        },
    )

    lab_specs = {
        "LB-01": (
            "LB1",
            349,
            True,
            {
                "USUBJID": "S05003",
                "LBTEST": "血红蛋白（Hb）",
                "LBORRESN": "129",
                "LBORNRLO": ">=130",
                "LBORNRHI": "<=175",
                "LBORRESU": "g/L",
            },
        ),
        "LB-02": (
            "LB2",
            236,
            True,
            {
                "USUBJID": "S01008",
                "LBTEST": "间接胆红素",
                "LBORRESN": "13.8",
                "LBORNRLO": ">=1.7",
                "LBORNRHI": "<=10.2",
                "LBSIG": "正常",
            },
        ),
        "LB-03": (
            "LB1",
            2,
            False,
            {
                "USUBJID": "S01003",
                "LBTEST": "白细胞计数（WBC）",
                "LBORRESN": "9.78",
                "LBORNRLO": ">=3.5",
                "LBORNRHI": "<=9.5",
                "LBSIG": "异常有临床意义",
            },
        ),
        "LB-04": (
            "LB1",
            16,
            False,
            {
                "USUBJID": "S01003",
                "LBTEST": "单核细胞绝对值",
                "LBORRESN": "0.62",
                "LBORNRLO": ">=0.1",
                "LBORNRHI": "<=0.6",
                "LBSIG": "异常无临床意义",
            },
        ),
    }
    for case_id, (sheet_name, excel_row, expected_match, expected) in lab_specs.items():
        row = _located_row(
            listing_sources,
            "my009",
            sheet_name,
            excel_row,
        )
        cases[case_id] = RealListingCase(
            case_id=case_id,
            classification="real_positive" if expected_match else "real_negative",
            expected_match=expected_match,
            rule=rules["my009_lab_significance"],
            current_record=_lab_record(row),
            observed_domains=("LB",),
            related_records={},
            raw_checks=(RawCheck(row=row, expected_values=expected),),
            rows={"lb": row},
            expected_current_locators=(row.locator,),
            expected_related_locators={},
        )

    cm_01 = _located_row(listing_sources, "my009", "CM1", 5)
    cm_01_v2 = _located_row(listing_sources, "my009", "SV", 9)
    cases["CM-01"] = RealListingCase(
        case_id="CM-01",
        classification="real_negative",
        expected_match=False,
        rule=rules["my009_allowed_steroid"],
        current_record={
            "USUBJID": cm_01.values["USUBJID"],
            "CM1TRT": cm_01.values["CM1TRT"],
            "CM1DOSE": cm_01.values["CM1DOSE"],
            "CM1DOSU": cm_01.values["CM1DOSU"],
            "CM1FRQ": cm_01.values["CM1FRQ"],
            "CM1STDAT": cm_01.values["CM1STDAT"],
            "VISDAT": cm_01_v2.values["VISDAT"],
            "__source_locator__": [cm_01.locator, cm_01_v2.locator],
        },
        observed_domains=("CM", "SV"),
        related_records={"SV": [_evidence_row(cm_01_v2)]},
        raw_checks=(
            _raw_check(
                cm_01,
                USUBJID="S01003",
                CM1TRT="醋酸泼尼松片",
                CM1DOSE="20",
                CM1DOSU="毫克",
                CM1FRQ="一次/日",
                CM1STDAT="2025-10-16",
            ),
            _raw_check(
                cm_01_v2,
                USUBJID="S01003",
                VISIT="访视2(D-7)",
                VISDAT="2025-12-03",
            ),
        ),
        rows={"cm": cm_01, "v2": cm_01_v2},
        expected_current_locators=(cm_01.locator, cm_01_v2.locator),
        expected_related_locators={"SV": (cm_01_v2.locator,)},
    )

    cm_02 = _located_row(listing_sources, "my009", "CM1", 30)
    cm_02_v2 = _located_row(listing_sources, "my009", "SV", 75)
    cases["CM-02"] = RealListingCase(
        case_id="CM-02",
        classification="real_negative",
        expected_match=False,
        rule=rules["my009_prohibited_biologic"],
        current_record={
            "USUBJID": cm_02.values["USUBJID"],
            "CM1TRT": cm_02.values["CM1TRT"],
            "CM1TRT__13": cm_02.values["CM1TRT__13"],
            "CM1STDAT": cm_02.values["CM1STDAT"],
            "CM1ENDAT": cm_02.values["CM1ENDAT"],
            "VISDAT": cm_02_v2.values["VISDAT"],
            "__source_locator__": [cm_02.locator, cm_02_v2.locator],
        },
        observed_domains=("CM", "SV"),
        related_records={"SV": [_evidence_row(cm_02_v2)]},
        raw_checks=(
            _raw_check(
                cm_02,
                USUBJID="S05003",
                CM1TRT="维得利珠单抗",
                CM1TRT__13="单克隆抗体",
                CM1ENDAT="2025-08-29",
            ),
            _raw_check(
                cm_02_v2,
                USUBJID="S05003",
                VISIT="访视2(D-7)",
                VISDAT="2026-02-28",
            ),
        ),
        rows={"cm": cm_02, "v2": cm_02_v2},
        expected_current_locators=(cm_02.locator, cm_02_v2.locator),
        expected_related_locators={"SV": (cm_02_v2.locator,)},
    )

    visit_specs = {
        "SV-01": (223, 225, True, "S01020"),
        "SV-02": (92, 94, False, "S01008"),
    }
    for case_id, (d1_row, d29_row, expected_match, subject_id) in visit_specs.items():
        d1 = _located_row(listing_sources, "rux", rux_sv_sheet, d1_row)
        d29 = _located_row(listing_sources, "rux", rux_sv_sheet, d29_row)
        cases[case_id] = RealListingCase(
            case_id=case_id,
            classification="real_positive" if expected_match else "real_negative",
            expected_match=expected_match,
            rule=rules["rux_visit_window"],
            current_record={
                "USUBJID": d29.values["SUBJID"],
                "SVDAT": d29.values["SVDAT"],
                "SVDATPE": d29.values["SVDATPE"],
                "SVDATPL": d29.values["SVDATPL"],
                "__source_locator__": d29.locator,
            },
            observed_domains=("SV",),
            related_records={"SV": [_evidence_row(d1)]},
            raw_checks=(
                _raw_check(
                    d1,
                    SUBJID=subject_id,
                    VISTOID="D1",
                    SVDAT=d1.values["SVDAT"],
                ),
                _raw_check(
                    d29,
                    SUBJID=subject_id,
                    VISTOID="D29",
                    SVDAT=d29.values["SVDAT"],
                    SVDATPE=d29.values["SVDATPE"],
                    SVDATPL=d29.values["SVDATPL"],
                ),
            ),
            rows={"d1": d1, "d29": d29},
            expected_current_locators=(d29.locator,),
            expected_related_locators={"SV": (d1.locator,)},
        )

    adherence_specs = {
        "ADH-01": (
            593,
            True,
            {
                "SUBJID": "S09001",
                "DAADOFRQ": "21",
                "DAPDOFRQ": "28",
                "DABMECO": "75",
            },
        ),
        "ADH-02": (
            997,
            False,
            {
                "SUBJID": "S13052",
                "DAADOFRQ": "20",
                "DAPDOFRQ": "25",
                "DABMECO": "80",
            },
        ),
    }
    for case_id, (excel_row, expected_match, expected) in adherence_specs.items():
        row = _located_row(
            listing_sources,
            "rux",
            rux_dab_sheet,
            excel_row,
        )
        cases[case_id] = RealListingCase(
            case_id=case_id,
            classification="real_positive" if expected_match else "real_negative",
            expected_match=expected_match,
            rule=rules["rux_adherence"],
            current_record={
                "USUBJID": row.values["SUBJID"],
                "DAADOFRQ": row.values["DAADOFRQ"],
                "DAPDOFRQ": row.values["DAPDOFRQ"],
                "DABMECO": row.values["DABMECO"],
                "__source_locator__": row.locator,
            },
            observed_domains=("DA",),
            related_records={},
            raw_checks=(RawCheck(row=row, expected_values=expected),),
            rows={"dab": row},
            expected_current_locators=(row.locator,),
            expected_related_locators={},
        )

    dq_01 = _located_row(listing_sources, "rux", rux_dab_sheet, 601)
    recalculated = (
        Decimal(dq_01.values["DAADOFRQ"])
        / Decimal(dq_01.values["DAPDOFRQ"])
        * Decimal(100)
    )
    absolute_delta = abs(Decimal(dq_01.values["DABMECO"]) - recalculated)
    cases["DQ-01"] = RealListingCase(
        case_id="DQ-01",
        classification="real_positive",
        expected_match=True,
        rule=rules["rux_adherence_arithmetic"],
        current_record={
            "USUBJID": dq_01.values["SUBJID"],
            "DAADOFRQ": dq_01.values["DAADOFRQ"],
            "DAPDOFRQ": dq_01.values["DAPDOFRQ"],
            "DABMECO": dq_01.values["DABMECO"],
            "DAB_ABS_PERCENTAGE_POINT_DELTA": str(absolute_delta),
            "__source_locator__": dq_01.locator,
            "__auditable_base_values__": {
                "DAB_ABS_PERCENTAGE_POINT_DELTA": {
                    "source_type": "auditable_base_value",
                    "input_fields": ["DAADOFRQ", "DAPDOFRQ", "DABMECO"],
                    "input_locators": [dq_01.locator],
                    "calculation_expression": (
                        "abs(decimal(DABMECO) - decimal(DAADOFRQ) / "
                        "decimal(DAPDOFRQ) * 100)"
                    ),
                    "unit": "percentage points",
                    "calculated_value": str(absolute_delta),
                }
            },
        },
        observed_domains=("DA",),
        related_records={},
        raw_checks=(
            _raw_check(
                dq_01,
                SUBJID="S09002",
                DAADOFRQ="55",
                DAPDOFRQ="56",
                DABMECO="100",
                DABMECO_UNIT="%",
            ),
        ),
        rows={"dab": dq_01},
        expected_current_locators=(dq_01.locator,),
        expected_related_locators={},
    )

    ae_03 = _located_row(listing_sources, "my009", "AE", 18)
    ae_03_ex_rows = _subject_rows(
        listing_sources, "my009", "EX", "USUBJID", "S05003"
    )
    ae_03_da_rows = _subject_rows(
        listing_sources, "my009", "DA", "USUBJID", "S05003"
    )
    ae_03_sv_rows = _subject_rows(
        listing_sources, "my009", "SV", "USUBJID", "S05003"
    )
    ae_03_da_v2 = next(row for row in ae_03_da_rows if row.excel_row == 19)
    ae_03_sv_v2 = next(row for row in ae_03_sv_rows if row.excel_row == 75)
    ae_03_ex_d1 = next(row for row in ae_03_ex_rows if row.excel_row == 19)
    cases["AE-03"] = RealListingCase(
        case_id="AE-03",
        classification="real_indeterminate",
        expected_match=None,
        rule=rules["my009_induction_ae_boundary"],
        current_record={
            "USUBJID": ae_03.values["USUBJID"],
            "AETERM": ae_03.values["AETERM"],
            "AESTDAT": ae_03.values["AESTDAT"],
            "__source_locator__": ae_03.locator,
        },
        observed_domains=("AE", "EX", "DA", "SV"),
        related_records={
            "EX": [_evidence_row(row) for row in ae_03_ex_rows],
            "DA": [_evidence_row(row) for row in ae_03_da_rows],
            "SV": [_evidence_row(row) for row in ae_03_sv_rows],
        },
        raw_checks=(
            _raw_check(
                ae_03,
                USUBJID="S05003",
                AETERM="痔疮",
                AESTDAT="2026-03-02",
                EPOCH="导入期",
            ),
            _raw_check(
                ae_03_sv_v2,
                USUBJID="S05003",
                VISIT="访视2(D-7)",
                VISDAT="2026-02-28",
            ),
            _raw_check(
                ae_03_da_v2,
                USUBJID="S05003",
                VISIT="访视2(D-7)",
                DADAT="2026-02-28 14:59",
            ),
            _raw_check(
                ae_03_ex_d1,
                USUBJID="S05003",
                VISIT="访视3(D1)",
                EXDAT="2026-03-07",
                EXTIM="16:06",
            ),
        ),
        rows={
            "ae": ae_03,
            "da_v2": ae_03_da_v2,
            "sv_v2": ae_03_sv_v2,
            "ex_d1": ae_03_ex_d1,
        },
        expected_current_locators=(ae_03.locator,),
        expected_related_locators={
            "EX": tuple(row.locator for row in ae_03_ex_rows),
            "DA": tuple(row.locator for row in ae_03_da_rows),
            "SV": tuple(row.locator for row in ae_03_sv_rows),
        },
    )

    assert tuple(case_id for case_id in DETERMINATE_CASE_IDS) == tuple(
        case_id for case_id in cases if case_id != "AE-03"
    )
    return cases


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _assert_auditable_base_values(record: Mapping[str, Any]) -> None:
    for field_name, audit in record.get("__auditable_base_values__", {}).items():
        assert audit["source_type"] == "auditable_base_value"
        assert audit["input_fields"]
        assert audit["input_locators"]
        assert all(
            str(locator).startswith("listing:")
            and ":sheet:" in str(locator)
            and ":row:" in str(locator)
            for locator in audit["input_locators"]
        )
        assert audit["calculation_expression"]
        assert audit["unit"]
        assert str(record[field_name]) == str(audit["calculated_value"])


def _assert_case_oracle(case: RealListingCase) -> None:
    if case.case_id in {"AE-01", "AE-02"}:
        ae = case.rows["ae"]
        first_ec = case.rows["first_ec"]
        ec_records = case.related_records["EC"]
        mh_records = case.related_records["MH"]
        first_actual = min(_date(row["ECADAT"]) for row in ec_records)
        event_date = _date(ae.values["AESTDAT"])
        assert first_actual == _date(first_ec.values["ECADAT"])
        assert case.current_record["FIRST_ECADAT"] == first_actual.isoformat()
        assert len(ec_records) == (165 if case.case_id == "AE-01" else 174)
        assert len(mh_records) == (5 if case.case_id == "AE-01" else 8)
        same_term_same_day = [
            row
            for row in mh_records
            if row["SUBJID"] == ae.values["SUBJID"]
            and row["MHTERM"] == ae.values["AETERM"]
            and row["MHSTDAT"] == ae.values["AESTDAT"]
        ]
        assert same_term_same_day == []
        if case.case_id == "AE-01":
            assert (event_date - first_actual).days == -7
            assert all(row["MHTERM"] != "皮肤瘙痒" for row in mh_records)
        else:
            assert (event_date - first_actual).days == 143
            same_term = case.rows["same_term_mh"]
            assert same_term.excel_row == 76
            assert same_term.values["MHSTDAT"] != ae.values["AESTDAT"]
        return

    if case.case_id.startswith("LB-"):
        row = case.rows["lb"]
        result = Decimal(row.values["LBORRESN"])
        lower = _decimal_bound(row.values["LBORNRLO"])
        upper = _decimal_bound(row.values["LBORNRHI"])
        lower_delta = result - lower
        upper_delta = result - upper
        assert case.current_record["LBORRESN_MINUS_LBORNRLO"] == str(lower_delta)
        assert case.current_record["LBORRESN_MINUS_LBORNRHI"] == str(upper_delta)
        assert result < lower or result > upper
        if case.case_id == "LB-01":
            assert (result, lower, upper, lower_delta) == (
                Decimal("129"),
                Decimal("130"),
                Decimal("175"),
                Decimal("-1"),
            )
            assert row.values.get("LBSIG", "") == ""
        elif case.case_id == "LB-02":
            assert (result, upper, upper_delta) == (
                Decimal("13.8"),
                Decimal("10.2"),
                Decimal("3.6"),
            )
            assert row.values["LBSIG"] == "正常"
        elif case.case_id == "LB-03":
            assert (result, upper, upper_delta) == (
                Decimal("9.78"),
                Decimal("9.5"),
                Decimal("0.28"),
            )
            assert row.values["LBSIG"] == "异常有临床意义"
        else:
            assert (result, upper, upper_delta) == (
                Decimal("0.62"),
                Decimal("0.6"),
                Decimal("0.02"),
            )
            assert row.values["LBSIG"] == "异常无临床意义"
        return

    if case.case_id == "CM-01":
        cm = case.rows["cm"]
        v2 = case.rows["v2"]
        stable_days = (_date(v2.values["VISDAT"]) - _date(cm.values["CM1STDAT"])).days
        assert Decimal(cm.values["CM1DOSE"]) == Decimal("20")
        assert cm.values["CM1DOSU"] == "毫克"
        assert cm.values["CM1FRQ"] == "一次/日"
        assert stable_days == 48
        assert stable_days >= 14
        return

    if case.case_id == "CM-02":
        cm = case.rows["cm"]
        v2 = case.rows["v2"]
        assert (
            _date(cm.values["CM1ENDAT"]) - _date(v2.values["VISDAT"])
        ).days == -183
        assert _date(cm.values["CM1ENDAT"]) < _date(v2.values["VISDAT"])
        return

    if case.case_id in {"SV-01", "SV-02"}:
        d1 = case.rows["d1"]
        d29 = case.rows["d29"]
        d1_date = _date(d1.values["SVDAT"])
        actual = _date(d29.values["SVDAT"])
        target = d1_date + timedelta(days=28)
        earliest = _date(d29.values["SVDATPE"])
        latest = _date(d29.values["SVDATPL"])
        assert earliest == target - timedelta(days=3)
        assert latest == target + timedelta(days=3)
        if case.case_id == "SV-01":
            assert (actual - d1_date).days == 35
            assert (actual - target).days == 7
            assert actual > latest
        else:
            assert (actual - d1_date).days == 31
            assert (actual - target).days == 3
            assert actual == latest
        return

    if case.case_id in {"ADH-01", "ADH-02"}:
        row = case.rows["dab"]
        ratio = (
            Decimal(row.values["DAADOFRQ"])
            / Decimal(row.values["DAPDOFRQ"])
            * Decimal(100)
        )
        assert ratio == (Decimal("75") if case.case_id == "ADH-01" else Decimal("80"))
        assert Decimal(row.values["DABMECO"]) == ratio
        return

    if case.case_id == "DQ-01":
        row = case.rows["dab"]
        recalculated = (
            Decimal(row.values["DAADOFRQ"])
            / Decimal(row.values["DAPDOFRQ"])
            * Decimal(100)
        )
        reported = Decimal(row.values["DABMECO"])
        absolute_delta = abs(reported - recalculated)
        assert recalculated == Decimal(5500) / Decimal(56)
        assert recalculated.quantize(Decimal("0.01")) == Decimal("98.21")
        assert reported == Decimal("100")
        assert case.current_record["DAB_ABS_PERCENTAGE_POINT_DELTA"] == str(
            absolute_delta
        )
        assert absolute_delta > 0
        return

    raise AssertionError(f"missing oracle for {case.case_id}")


def _trace_nodes(trace: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    nodes = [trace]
    for child in trace.get("children", ()):
        if isinstance(child, Mapping):
            nodes.extend(_trace_nodes(child))
    return nodes


def _trace(
    result: Any,
    operator: str,
    *,
    field: str = "",
    other_field: str = "",
) -> Mapping[str, Any]:
    trigger = result.evidence["predicate_trace"]["trigger"]
    for node in _trace_nodes(trigger):
        if node.get("operator") != operator:
            continue
        if field and node.get("field") != field:
            continue
        if other_field and node.get("other_field") != other_field:
            continue
        return node
    raise AssertionError(
        f"trace not found: operator={operator}, field={field}, other={other_field}"
    )


def _assert_evaluation_reason(case: RealListingCase, result: Any) -> None:
    if case.case_id == "AE-01":
        assert _trace(result, "date_compare", field="AESTDAT")["computed_delta_days"] == -7
        missing_mh = _trace(result, "no_corresponding_record")
        assert missing_mh["state"] == "true"
        assert missing_mh["matching_record_count"] == 0
        assert tuple(missing_mh["searched_source_locators"]) == (
            case.expected_related_locators["MH"]
        )
    elif case.case_id == "AE-02":
        timing = _trace(result, "date_compare", field="AESTDAT")
        assert timing["state"] == "false"
        assert timing["computed_delta_days"] == 143
    elif case.case_id.startswith("LB-"):
        lower = _trace(result, "lt", field="LBORRESN_MINUS_LBORNRLO")
        upper = _trace(result, "gt", field="LBORRESN_MINUS_LBORNRHI")
        assert "calculated" in {lower["calculation_status"], upper["calculation_status"]}
        if case.case_id == "LB-01":
            assert lower["state"] == "true"
            assert _trace(result, "missing", field="LBSIG")["state"] == "true"
        elif case.case_id == "LB-02":
            assert upper["state"] == "true"
            assert _trace(result, "eq", field="LBSIG")["state"] == "true"
        else:
            assert upper["state"] == "true"
            assert _trace(result, "missing", field="LBSIG")["state"] == "false"
            assert _trace(result, "eq", field="LBSIG")["state"] == "false"
    elif case.case_id == "CM-01":
        assert _trace(result, "gt", field="CM1DOSE")["state"] == "false"
        stable = _trace(result, "date_delta_range", field="VISDAT")
        assert stable["state"] == "true"
        assert stable["computed_delta_days"] == 48
    elif case.case_id == "CM-02":
        overlap = _trace(result, "date_compare", field="CM1ENDAT")
        assert overlap["state"] == "false"
        assert overlap["computed_delta_days"] == -183
    elif case.case_id == "SV-01":
        late = _trace(
            result,
            "date_compare",
            field="SVDAT",
            other_field="SVDATPL",
        )
        assert late["state"] == "true"
        assert late["computed_delta_days"] == 4
    elif case.case_id == "SV-02":
        early = _trace(
            result,
            "date_compare",
            field="SVDAT",
            other_field="SVDATPE",
        )
        late = _trace(
            result,
            "date_compare",
            field="SVDAT",
            other_field="SVDATPL",
        )
        assert early["state"] == "false"
        assert late["state"] == "false"
        assert late["computed_delta_days"] == 0
    elif case.case_id in {"ADH-01", "ADH-02"}:
        ratio = _trace(result, "ratio_range")
        expected = 75.0 if case.case_id == "ADH-01" else 80.0
        assert ratio["computed_ratio"] == pytest.approx(expected)
        assert ratio["state"] == ("false" if case.case_id == "ADH-01" else "true")
    elif case.case_id == "DQ-01":
        mismatch = _trace(
            result,
            "gt",
            field="DAB_ABS_PERCENTAGE_POINT_DELTA",
        )
        assert mismatch["state"] == "true"
        assert mismatch["computed_left"] == pytest.approx(1.7857142857142858)
    else:
        raise AssertionError(f"missing evaluation reason for {case.case_id}")


def test_real_listing_and_protocol_sources_are_frozen_for_candidate_not_conclusion(
    listing_sources: Mapping[str, Mapping[str, Any]],
    protocol_bundle: Mapping[str, Any],
) -> None:
    # A frozen source proves reproducibility; a trigger still is not a medical conclusion.
    assert LISTING_PARSER_VERSION == "listing_file_parser_v3_ooxml_metadata_recovery"
    assert listing_sources["rux"]["sha256"] == LISTING_SPECS["rux"]["sha256"]
    assert listing_sources["my009"]["sha256"] == LISTING_SPECS["my009"]["sha256"]
    assert {
        "AE--不良事件",
        "ECA--研究药物给药-实际用药",
        "MH--既往及现病史",
        "SV--访视日期",
        "DAB--研究药物回收",
    }.issubset(listing_sources["rux"]["sheets"])
    assert {"AE", "CM1", "DA", "EX", "LB1", "LB2", "SV"}.issubset(
        listing_sources["my009"]["sheets"]
    )
    for excerpt in protocol_bundle["excerpts"].values():
        expected = PROTOCOL_EXCERPT_SPECS[excerpt.key]
        assert (excerpt.source_key, excerpt.source_locator, excerpt.source_text) == expected


@pytest.mark.parametrize("case_id", DETERMINATE_CASE_IDS)
def test_real_listing_raw_rows_and_oracles_trigger_candidate_is_not_medical_conclusion(
    case_id: str,
    real_cases: Mapping[str, RealListingCase],
) -> None:
    case = real_cases[case_id]
    for raw_check in case.raw_checks:
        assert raw_check.row.sheet_name
        assert raw_check.row.excel_row >= 1
        assert raw_check.row.locator.endswith(
            f":sheet:{raw_check.row.sheet_name}:row:{raw_check.row.excel_row}"
        )
        for field_name, expected_value in raw_check.expected_values.items():
            assert raw_check.row.values.get(field_name, "") == expected_value

    _assert_auditable_base_values(case.current_record)
    _assert_case_oracle(case)

    all_evidence_locators = set(case.expected_current_locators)
    for locators in case.expected_related_locators.values():
        all_evidence_locators.update(locators)
    assert all(
        raw_check.row.locator in all_evidence_locators
        for raw_check in case.raw_checks
    )


@pytest.mark.parametrize("case_id", DETERMINATE_CASE_IDS)
def test_evaluate_record_expected_candidate_is_not_medical_conclusion(
    case_id: str,
    real_cases: Mapping[str, RealListingCase],
) -> None:
    case = real_cases[case_id]
    assert case.rule.status == "enabled"
    result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        case.rule,
        case.current_record,
        observed_domains=case.observed_domains,
        related_records=case.related_records,
    )

    assert result.matched is case.expected_match
    assert result.evidence["evaluation_state"] == (
        "true" if case.expected_match else "false"
    )
    assert result.evidence["evidence_ready"] is True
    assert result.evidence["medical_review_candidate_only"] is True
    assert tuple(result.evidence["current_record"]["source_locators"]) == (
        case.expected_current_locators
    )
    for domain, expected_locators in case.expected_related_locators.items():
        actual_locators = tuple(
            locator
            for record in result.evidence["related_records"][domain]
            for locator in record["source_locators"]
        )
        assert actual_locators == expected_locators

    assert result.protocol_source["source_locator"] == case.rule.source_locator
    assert result.protocol_source["source_text"] == case.rule.source_text
    assert all(ref.source_locator and ref.source_text for ref in case.rule.source_refs)
    _assert_evaluation_reason(case, result)


def test_ae_03_missing_first_actual_induction_use_is_indeterminate_not_conclusion(
    real_cases: Mapping[str, RealListingCase],
) -> None:
    # Dispensing and D1 administration are evidence, but neither is first induction use.
    case = real_cases["AE-03"]
    for raw_check in case.raw_checks:
        for field_name, expected_value in raw_check.expected_values.items():
            assert raw_check.row.values.get(field_name, "") == expected_value

    ae_date = _date(case.rows["ae"].values["AESTDAT"])
    dispensing_date = datetime.fromisoformat(
        case.rows["da_v2"].values["DADAT"]
    ).date()
    v2_date = _date(case.rows["sv_v2"].values["VISDAT"])
    d1_actual_date = _date(case.rows["ex_d1"].values["EXDAT"])
    assert (ae_date - dispensing_date).days == 2
    assert dispensing_date == v2_date
    assert (ae_date - d1_actual_date).days == -5
    assert "EXDAT" not in case.current_record

    ex_records = case.related_records["EX"]
    assert tuple(
        row["__source_locator__"] for row in ex_records
    ) == case.expected_related_locators["EX"]
    assert len(ex_records) == 2
    assert {row["VISIT"] for row in ex_records} == {"访视3(D1)", "访视4(D7)"}
    assert not any(
        "D-7" in row["VISIT"] or "导入期" in row["VISIT"]
        for row in ex_records
    )

    result = object.__new__(MonitoringProtocolRuleService).evaluate_record(
        case.rule,
        case.current_record,
        observed_domains=case.observed_domains,
        related_records=case.related_records,
    )
    trigger = result.evidence["predicate_trace"]["trigger"]
    assert case.rule.status == "enabled"
    assert result.matched is False
    assert result.evidence["evaluation_state"] == "indeterminate"
    assert trigger["state"] == "indeterminate"
    assert trigger["field"] == "AESTDAT"
    assert trigger["other_field"] == "EXDAT"
    assert trigger["other_field_value"] is None
    assert trigger["calculation_status"] == "invalid_date_operand"
    assert result.evidence["medical_review_candidate_only"] is True
    assert result.protocol_source["source_locator"] == "docx:paragraph:1356"
    assert "开始服用导入期试验用药物之前" in result.protocol_source["source_text"]


def test_real_listing_fixtures_do_not_use_conclusion_placeholders(
    real_cases: Mapping[str, RealListingCase],
) -> None:
    # Raw fields and auditable calculations support candidates, not medical conclusions.
    for case in real_cases.values():
        payload = repr(
            {
                "rule": case.rule.public_dict(),
                "record": case.current_record,
                "related_records": case.related_records,
            }
        )
        for forbidden_field in FORBIDDEN_PLACEHOLDER_FIELDS:
            assert forbidden_field not in payload


def _real_rule_with_confirmed_facts(
    repository: MonitoringProtocolRuleRepository,
    version: ProtocolSourceVersion,
    rule: MonitoringRuleDefinition,
) -> MonitoringRuleDefinition:
    """Rebind a real-source rule to persisted, medically confirmed protocol facts."""
    fact_types = _REAL_RULE_FACT_TYPES[rule.rule_key]
    assert len(fact_types) == len(rule.source_refs), rule.rule_key

    stored_facts: list[ProtocolFact] = []
    source_refs: list[RuleSourceReference] = []
    for index, (source_ref, fact_type) in enumerate(
        zip(rule.source_refs, fact_types),
        start=1,
    ):
        fact = repository.store_fact(
            ProtocolFact.create(
                project_id=version.project_id,
                protocol_version_id=version.protocol_version_id,
                fact_key=(
                    f"monitoring.{rule.rule_key}.source.{index}"
                ),
                fact_type=fact_type,
                status="medically_confirmed",
                title=f"{rule.title}的方案依据{index}",
                normalized_payload={
                    "rule_key": rule.rule_key,
                    "source_locator": source_ref.source_locator,
                    "source_excerpt_sha256": source_ref.source_text_sha256,
                },
                source_entry_id=source_ref.source_entry_id,
                source_locator=source_ref.source_locator,
                source_text=source_ref.source_text,
            )
        )
        stored_facts.append(fact)
        source_refs.append(
            RuleSourceReference.create(
                fact_revision_id=fact.fact_revision_id,
                source_entry_id=fact.source_entry_id,
                source_locator=fact.source_locator,
                source_text=fact.source_text,
            )
        )

    primary = source_refs[0]
    identity_seed = f"{version.project_id}:real-listing-fixture-v1"
    return MonitoringRuleDefinition.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        rule_key=rule.rule_key,
        rule_family=rule.rule_family,
        status="candidate",
        title=rule.title,
        executor=rule.executor,
        required_domains=rule.required_domains,
        preconditions=rule.preconditions,
        trigger_expression=rule.trigger_expression,
        exclusions=rule.exclusions,
        severity=rule.severity,
        confidence=rule.confidence,
        evidence_template=rule.evidence_template,
        fact_revision_ids=[fact.fact_revision_id for fact in stored_facts],
        source_entry_id=primary.source_entry_id,
        source_locator=primary.source_locator,
        source_text=primary.source_text,
        clinical_domain=rule.clinical_domain,
        source_refs=source_refs,
        field_lineage=rule.field_lineage,
        mapping_revision=f"{version.project_id}-real-listing-fixture-v1",
        mapping_content_sha256=sha256(
            f"{identity_seed}:mapping-content".encode("utf-8")
        ).hexdigest(),
        capability_manifest_sha256=sha256(
            f"{identity_seed}:capability-manifest".encode("utf-8")
        ).hexdigest(),
        effective_capabilities_sha256=sha256(
            f"{identity_seed}:effective-capabilities".encode("utf-8")
        ).hexdigest(),
    )


def _real_listing_gold_case(
    case: RealListingCase,
    *,
    project_id: str,
    rule: MonitoringRuleDefinition,
    source_key: str,
    source_entry_id: str,
    source_revision: str,
    batch_revision: str,
    authority: MonitoringGoldCaseAuthority,
    authoritative_batch_id: str,
) -> RuleGoldStandardCase:
    source_sha256 = LISTING_SPECS[source_key]["sha256"]
    evidence_locators = set(case.expected_current_locators)
    for locators in case.expected_related_locators.values():
        evidence_locators.update(locators)
    assert evidence_locators
    assert all(
        locator.startswith("listing:")
        and ":sheet:" in locator
        and ":row:" in locator
        for locator in evidence_locators
    )
    assert case.expected_match is not None

    def canonical_record(record: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(record)
        derived = record.get("__auditable_base_values__") or {}
        if not derived:
            return normalized
        canonical_derived: dict[str, dict[str, Any]] = {}
        for field_name, metadata in derived.items():
            matches = [
                binding
                for binding in rule.field_lineage.values()
                if binding["field"] == field_name
                and binding["lineage"]["source_type"] == "auditable_base_value"
            ]
            assert len(matches) == 1
            lineage = matches[0]["lineage"]
            input_fields = [
                rule.field_lineage[input_role]["field"]
                for input_role in lineage["input_field_roles"]
            ]
            canonical_derived[field_name] = {
                **dict(metadata),
                "source_type": "auditable_base_value",
                "input_fields": input_fields,
                "calculation_expression": lineage["calculation_expression"],
            }
        normalized["__auditable_base_values__"] = canonical_derived
        return normalized

    current_record = canonical_record(case.current_record)
    related_records = {
        domain: [canonical_record(record) for record in records]
        for domain, records in case.related_records.items()
    }
    roles_by_locator: dict[str, set[str]] = {}
    records_by_role: dict[str, Mapping[str, Any]] = {
        "current": current_record
    }

    def record_locators(record: Mapping[str, Any]) -> tuple[str, ...]:
        raw = record.get("__source_locator__")
        if isinstance(raw, str):
            return (raw,)
        assert isinstance(raw, list)
        return tuple(raw)

    for locator in record_locators(current_record):
        roles_by_locator.setdefault(locator, set()).add("current")
    for domain, records in sorted(related_records.items()):
        for index, record in enumerate(records):
            role = f"related:{domain}:{index}"
            records_by_role[role] = record
            for locator in record_locators(record):
                roles_by_locator.setdefault(locator, set()).add(role)
    assert set(roles_by_locator) == evidence_locators

    rows_by_locator = {
        (
            f"listing:{row.source_locator['source_content_sha256']}:"
            f"sheet:{row.source_locator['sheet']}:row:{row.source_locator['row']}"
        ): row
        for row in authority.batch_repository.list_rows(authoritative_batch_id)
    }
    field_bindings_by_role: dict[str, set[str]] = {
        role: set() for role in records_by_role
    }
    bindings: list[RuleGoldSourceRowBinding] = []
    for locator in sorted(evidence_locators):
        row = rows_by_locator[locator]
        field_bindings: list[RuleGoldRecordFieldBinding] = []
        for role in sorted(roles_by_locator[locator]):
            record = records_by_role[role]
            derived_fields = set(
                (record.get("__auditable_base_values__") or {}).keys()
            )
            for record_field, value in record.items():
                if str(record_field).startswith("__") or record_field in derived_fields:
                    continue
                source_field = ""
                if (
                    record_field in row.data
                    and row.data[record_field] == value
                ):
                    source_field = record_field
                elif (
                    record_field == "USUBJID"
                    and row.data.get("SUBJID") == value
                ):
                    source_field = "SUBJID"
                if not source_field:
                    continue
                field_bindings.append(
                    RuleGoldRecordFieldBinding.create(
                        record_role=role,
                        record_field=record_field,
                        source_field=source_field,
                    )
                )
                field_bindings_by_role[role].add(record_field)
        bindings.append(
            RuleGoldSourceRowBinding.create(
                business_key=row.business_key,
                domain=row.domain,
                source_locator=locator,
                row_fingerprint=row.row_fingerprint,
                record_roles=roles_by_locator[locator],
                field_bindings=field_bindings,
            )
        )
    for role, record in records_by_role.items():
        derived_fields = set(
            (record.get("__auditable_base_values__") or {}).keys()
        )
        expected_fields = {
            str(field)
            for field in record
            if not str(field).startswith("__") and field not in derived_fields
        }
        assert field_bindings_by_role[role] == expected_fields
    source_row_bindings = tuple(bindings)
    return RuleGoldStandardCase.create(
        project_id=project_id,
        rule_key=case.rule.rule_key,
        rule_revision_id=rule.rule_revision_id,
        source_entry_id=source_entry_id,
        source_content_sha256=source_sha256,
        source_revision=source_revision,
        batch_revision=batch_revision,
        case_label=f"{case.case_id}: frozen real listing",
        input_record=current_record,
        previous_record={},
        related_records={
            domain: [dict(row) for row in records]
            for domain, records in related_records.items()
        },
        observed_domains=case.observed_domains,
        expected_match=case.expected_match,
        medical_rationale=(
            f"{case.case_id}：由冻结的真实 listing 原始行及方案原文定位构成；"
            "仅验证确定性医学复核候选规则，不构成医学结论。"
        ),
        evidence_locators=evidence_locators,
        source_row_bindings=source_row_bindings,
    )


def _authoritative_listing_batch(
    *,
    root: Path,
    source_key: str,
    project_id: str,
    parsed_sheets: Mapping[str, Any],
) -> tuple[MonitoringGoldCaseAuthority, str, str, str, str]:
    spec = LISTING_SPECS[source_key]
    source_entry_id = f"listing-{source_key}-{spec['sha256'][:16]}"
    registry_store = _RegistryReader(
        (
            SourceRegistrationResult(
                entry=SourceRegistryEntry(
                    entry_id=source_entry_id,
                    project_id=project_id,
                    module="medical_monitoring",
                    source_kind="edc_data_listing",
                    public_title=spec["path"].name,
                    content_hash=spec["sha256"],
                    size_bytes=spec["path"].stat().st_size,
                    parser_status="parsed",
                    parser_version=LISTING_PARSER_VERSION,
                    created_at=datetime.now(timezone.utc),
                ),
                spans=[],
            ),
        )
    )
    batch_repository = MonitoringBatchRepository(
        root / "monitoring_batches.sqlite3",
        root / "monitoring_batch_objects",
    )
    source = batch_repository.register_source(
        project_id=project_id,
        source_entry_id=source_entry_id,
        validation_id=f"validation-{source_key}-1",
        validation_revision=1,
        validator_version="source-content-v2",
        validation_use_status="allowed",
        role="edc_data_listing",
        source_class="raw_full_snapshot",
        file_path=spec["path"],
        parser_version=LISTING_PARSER_VERSION,
    )
    domains = tuple(
        sorted(
            sheet_name.upper()
            for sheet_name, sheet in parsed_sheets.items()
            if sheet.rows
        )
    )
    rows = tuple(
        {
            "business_key": f"raw:{sheet_name}:{row_number}",
            "domain": sheet_name.upper(),
            "data": dict(row),
            "source_locator": {
                "source_entry_id": source_entry_id,
                "source_content_sha256": spec["sha256"],
                "sheet": sheet_name,
                "row": row_number,
            },
        }
        for sheet_name, sheet in sorted(parsed_sheets.items())
        for row_number, row in zip(sheet.row_numbers, sheet.rows)
    )
    created = batch_repository.create_batch(
        project_id=project_id,
        idempotency_key=f"{source_key}:authority:create",
        expected_domains=domains,
    )
    attached = batch_repository.attach_source(
        batch_id=created.batch.batch_id,
        source_id=source.source_id,
        expected_version=created.batch.version,
        idempotency_key=f"{source_key}:authority:attach",
    )
    materialized = batch_repository.replace_rows(
        batch_id=created.batch.batch_id,
        rows=rows,
        expected_version=attached.batch.version,
        idempotency_key=f"{source_key}:authority:rows",
    )
    parsed = batch_repository.transition_batch(
        batch_id=created.batch.batch_id,
        target_state="parsed",
        expected_version=materialized.batch.version,
        idempotency_key=f"{source_key}:authority:parsed",
    )
    evidenced = batch_repository.record_validation_evidence(
        batch_id=created.batch.batch_id,
        mapping_revision=f"{source_key}-raw-row-preserving-v1",
        mapping={"mode": "raw_row_preserving", "source_hash": spec["sha256"]},
        expected_domains=domains,
        full_snapshot_proof={
            "confirmed": True,
            "basis": "完整原始 listing 的全部工作表及全部数据行",
            "confirmed_by": "medical_test_fixture",
        },
        expected_version=parsed.batch.version,
        idempotency_key=f"{source_key}:authority:evidence",
    )
    validated = batch_repository.transition_batch(
        batch_id=created.batch.batch_id,
        target_state="validated",
        expected_version=evidenced.batch.version,
        idempotency_key=f"{source_key}:authority:validated",
    )
    confirmed = batch_repository.transition_batch(
        batch_id=created.batch.batch_id,
        target_state="confirmed",
        expected_version=validated.batch.version,
        idempotency_key=f"{source_key}:authority:confirmed",
    )
    frozen = batch_repository.transition_batch(
        batch_id=created.batch.batch_id,
        target_state="frozen",
        expected_version=confirmed.batch.version,
        idempotency_key=f"{source_key}:authority:frozen",
    )
    return (
        MonitoringGoldCaseAuthority(registry_store, batch_repository),
        source_entry_id,
        monitoring_source_revision(source),
        monitoring_batch_revision(frozen.batch.batch_id, frozen.batch.version),
        frozen.batch.batch_id,
    )


@pytest.mark.parametrize(
    ("source_key", "case_ids"),
    (
        (
            "rux",
            ("AE-01", "AE-02", "SV-01", "SV-02", "ADH-01", "ADH-02", "DQ-01"),
        ),
        (
            "my009",
            ("LB-01", "LB-02", "LB-03", "LB-04", "CM-01", "CM-02"),
        ),
    ),
)
def test_real_listing_candidates_cannot_bypass_p7c_release_coverage(
    source_key: str,
    case_ids: tuple[str, ...],
    listing_sources: Mapping[str, Mapping[str, Any]],
    protocol_bundle: Mapping[str, Any],
    real_cases: Mapping[str, RealListingCase],
) -> None:
    """A published pack requires only repository-registered real listing evidence."""
    base_version = protocol_bundle["versions"][source_key]
    version = replace(
        base_version,
        applicability_status="project_effective_confirmed",
        operational_effective_from="2026-01-01",
    )
    project_cases = tuple(real_cases[case_id] for case_id in case_ids)
    assert all(case.expected_match is not None for case in project_cases)
    assert all(case.rule.project_id == version.project_id for case in project_cases)
    assert "AE-03" not in case_ids
    if source_key == "my009":
        assert real_cases["AE-03"].expected_match is None

    source_rules = {
        case.rule.rule_key: case.rule for case in project_cases
    }
    assert {
        case.rule.rule_key for case in project_cases
    } == set(source_rules)

    with TemporaryDirectory(prefix=f"monitoring-{source_key}-") as directory:
        root = Path(directory)
        (
            authority,
            source_entry_id,
            source_revision,
            batch_revision,
            authoritative_batch_id,
        ) = _authoritative_listing_batch(
            root=root,
            source_key=source_key,
            project_id=version.project_id,
            parsed_sheets=listing_sources[source_key]["sheets"],
        )
        repository = MonitoringProtocolRuleRepository(
            root / "real-listing-lifecycle.sqlite3",
            gold_case_authority=authority.validate,
        )
        version = repository.register_protocol_version(version)
        candidate_rules = tuple(
            _real_rule_with_confirmed_facts(repository, version, rule)
            for _, rule in sorted(source_rules.items())
        )
        assert all(rule.status == "candidate" for rule in candidate_rules)
        for rule in candidate_rules:
            for binding in rule.field_lineage.values():
                lineage = binding["lineage"]
                if lineage["source_type"] != "auditable_base_value":
                    continue
                assert "unit" not in lineage
                assert (
                    ("unit_literal" in lineage)
                    != ("unit_field_role" in lineage)
                )
        lifecycle = MonitoringRuleLifecycleService(
            repository,
            clock=lambda: "2026-07-29T06:00:00+00:00",
        )
        draft = lifecycle.create_draft(
            project_id=version.project_id,
            protocol_version_id=version.protocol_version_id,
            rules=candidate_rules,
            created_by="medical_rule_author",
        )
        confirmed_rules = tuple(
            lifecycle.confirm_rule(
                rule.rule_revision_id,
                expected_state_version=rule.state_version,
                confirmed_by="medical_manager",
            )
            for rule in candidate_rules
        )
        assert all(rule.status == "confirmed" for rule in confirmed_rules)
        shadow = lifecycle.start_shadow(
            draft.rule_pack_id,
            started_by="shadow_operator",
        )

        gold_cases = tuple(
            _real_listing_gold_case(
                case,
                project_id=version.project_id,
                rule={
                    item.rule_key: item for item in confirmed_rules
                }[case.rule.rule_key],
                source_key=source_key,
                source_entry_id=source_entry_id,
                source_revision=source_revision,
                batch_revision=batch_revision,
                authority=authority,
                authoritative_batch_id=authoritative_batch_id,
            )
            for case in project_cases
        )
        assert {
            case.rule_key for case in gold_cases
        } == {rule.rule_key for rule in confirmed_rules}

        service = MonitoringProtocolRuleService(repository)
        external_run = service.run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id=f"{source_key}-external-temporary",
            cases=gold_cases,
        )
        assert external_run.persisted is False
        assert external_run.trusted_for_release is False
        assert external_run.release_gate_eligible is False
        assert repository.shadow_runs(
            version.project_id,
            rule_pack_id=shadow.rule_pack_id,
        ) == ()
        with pytest.raises(
            RulePackLifecycleError,
            match="repository-registered shadow run",
        ):
            lifecycle.confirm_shadow(
                shadow.rule_pack_id,
                shadow_run_id=external_run.shadow_run_id,
                confirmed_by="medical_manager",
            )

        if source_key == "rux":
            source_case = gold_cases[0]
            forged_input = dict(source_case.input_record)
            forged_derived = dict(
                forged_input.get("__auditable_base_values__") or {}
            )
            forged_input["FORGED_RULE_INPUT"] = "伪造规则驱动值"
            forged_derived["FORGED_RULE_INPUT"] = {
                "source_type": "auditable_base_value",
                "input_fields": ["USUBJID"],
                "input_locators": list(source_case.evidence_locators),
                "calculation_expression": "minimum(raw_usubjid)",
                "unit": "text",
                "calculated_value": "伪造规则驱动值",
            }
            forged_input["__auditable_base_values__"] = forged_derived
            forged_case = RuleGoldStandardCase.create(
                project_id=source_case.project_id,
                rule_key=source_case.rule_key,
                rule_revision_id=source_case.rule_revision_id,
                source_entry_id=source_case.source_entry_id,
                source_content_sha256=source_case.source_content_sha256,
                source_revision=source_case.source_revision,
                batch_revision=source_case.batch_revision,
                case_label="forged case-declared formula",
                input_record=forged_input,
                previous_record=source_case.previous_record,
                related_records=source_case.related_records,
                observed_domains=source_case.observed_domains,
                expected_match=source_case.expected_match,
                medical_rationale=source_case.medical_rationale,
                evidence_locators=source_case.evidence_locators,
                source_row_bindings=source_case.source_row_bindings,
            )
            with pytest.raises(
                RulePackLifecycleError,
                match="not uniquely declared by the exact rule revision",
            ):
                repository.store_gold_cases((forged_case,))

            valid_derived = dict(
                source_case.input_record.get("__auditable_base_values__") or {}
            )
            derived_field = next(iter(valid_derived))
            duplicate_locator_metadata = dict(valid_derived[derived_field])
            duplicate_locator_metadata["input_locators"] = [
                *duplicate_locator_metadata["input_locators"],
                duplicate_locator_metadata["input_locators"][0],
            ]
            duplicate_locator_input = dict(source_case.input_record)
            duplicate_locator_input["__auditable_base_values__"] = {
                **valid_derived,
                derived_field: duplicate_locator_metadata,
            }
            duplicate_locator_case = RuleGoldStandardCase.create(
                project_id=source_case.project_id,
                rule_key=source_case.rule_key,
                rule_revision_id=source_case.rule_revision_id,
                source_entry_id=source_case.source_entry_id,
                source_content_sha256=source_case.source_content_sha256,
                source_revision=source_case.source_revision,
                batch_revision=source_case.batch_revision,
                case_label="duplicate derived input locator",
                input_record=duplicate_locator_input,
                previous_record=source_case.previous_record,
                related_records=source_case.related_records,
                observed_domains=source_case.observed_domains,
                expected_match=source_case.expected_match,
                medical_rationale=source_case.medical_rationale,
                evidence_locators=source_case.evidence_locators,
                source_row_bindings=source_case.source_row_bindings,
            )
            with pytest.raises(
                RulePackLifecycleError,
                match="duplicate_input_locators",
            ):
                repository.store_gold_cases((duplicate_locator_case,))

        stored_cases = repository.store_gold_cases(gold_cases)
        assert {case.case_id for case in stored_cases} == {
            case.case_id for case in gold_cases
        }
        assert repository.gold_cases(
            version.project_id,
            rule_revision_ids=[
                rule.rule_revision_id for rule in confirmed_rules
            ],
        ) == tuple(sorted(gold_cases, key=lambda case: (
            case.rule_key,
            case.case_label,
            case.case_id,
        )))

        trusted_run = service.run_shadow_validation(
            rule_pack_id=shadow.rule_pack_id,
            batch_id=authoritative_batch_id,
        )
        assert trusted_run.persisted is True
        assert trusted_run.trusted_for_release is True
        assert trusted_run.release_gate_eligible is False
        assert trusted_run.case_count == len(gold_cases)
        assert trusted_run.passed_count == len(gold_cases)
        assert trusted_run.failed_count == 0
        assert all(result.passed for result in trusted_run.results)

        confirmed = lifecycle.confirm_shadow(
            shadow.rule_pack_id,
            shadow_run_id=trusted_run.shadow_run_id,
            confirmed_by="medical_manager",
        )
        with pytest.raises(
            RulePackLifecycleError,
            match="not release eligible",
        ):
            lifecycle.publish(
                confirmed.rule_pack_id,
                published_by="medical_manager",
            )

        confirmed_by_key = {
            rule.rule_key: rule for rule in confirmed_rules
        }
        for case in project_cases:
            evaluation = service.evaluate_record(
                confirmed_by_key[case.rule.rule_key],
                case.current_record,
                observed_domains=case.observed_domains,
                related_records=case.related_records,
                allow_non_enabled=True,
                validation_mode="shadow",
            )
            assert evaluation.matched is case.expected_match
            assert evaluation.evidence["evidence_ready"] is True
