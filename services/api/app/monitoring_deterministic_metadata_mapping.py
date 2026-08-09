from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Optional, Sequence, Tuple


DETERMINISTIC_METADATA_MAPPING_VERSION = (
    "monitoring_deterministic_metadata_mapping.v3"
)
DETERMINISTIC_METADATA_PROFILE_ID = "monitoring-deterministic-metadata"
DETERMINISTIC_METADATA_PROVIDER = "workbench-system"
DETERMINISTIC_METADATA_MODEL = "deterministic-metadata-mapping-v1"
DETERMINISTIC_METADATA_PROVENANCE_SCHEMA_VERSION = (
    "monitoring_field_mapping_provenance_v1"
)
LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION = (
    "monitoring-listing-field-mapping-v7"
)
LEGACY_V7_DETERMINISTIC_REPAIR_REASON = (
    "v7_invalid_ai_output_repair"
)

_DOUBLE_UNDERSCORE_OID_RE = re.compile(r"^__[A-Z0-9_]+OID$")
_DOUBLE_UNDERSCORE_REPEAT_KEY_RE = re.compile(
    r"^__[A-Z0-9_]+REPEATKEY$"
)
_DUPLICATE_FORM_NAME_RE = re.compile(r"^FORMNM__\d+$")


@dataclass(frozen=True)
class DeterministicMetadataDecision:
    rule_id: str
    recommended_role: str
    rule_description: str

    def mapping(self, *, domain: str, source_field: str) -> dict[str, Any]:
        return {
            "domain": domain,
            "source_field": source_field,
            "recommended_role": self.recommended_role,
            "field_kind": "source_metadata",
            "confidence": 1.0,
            "uncertainty": (
                "该确定性规则仅确认字段的技术标识或关联角色，"
                "不解释字段值所代表的临床含义。"
            ),
            "user_action": (
                "如项目数据字典将该字段定义为业务采集值，"
                "请在映射草稿中修订。"
            ),
            "related_fields": [],
            "evidence_ids": [],
        }

    def provenance(self, *, domain: str, source_field: str) -> dict[str, str]:
        return {
            "domain": domain,
            "source_field": source_field,
            "origin": "deterministic_rule",
            "rule_id": self.rule_id,
            "rule_version": DETERMINISTIC_METADATA_MAPPING_VERSION,
            "rule_description": self.rule_description,
        }


_EXACT_FIELD_RULES: dict[str, DeterministicMetadataDecision] = {
    "DOMAIN": DeterministicMetadataDecision(
        rule_id="exact_domain_identifier",
        recommended_role="source_domain_identifier",
        rule_description="数据集或表单域标识字段。",
    ),
    "STUDYID": DeterministicMetadataDecision(
        rule_id="exact_study_identifier",
        recommended_role="study_identifier",
        rule_description="研究标识字段。",
    ),
    "__STUDYOID": DeterministicMetadataDecision(
        rule_id="exact_odm_study_oid",
        recommended_role="study_identifier",
        rule_description="ODM 研究对象标识字段。",
    ),
    "SITEID": DeterministicMetadataDecision(
        rule_id="exact_site_identifier",
        recommended_role="site_identifier",
        rule_description="研究中心标识字段。",
    ),
    "SITENM": DeterministicMetadataDecision(
        rule_id="exact_site_name",
        recommended_role="site_name",
        rule_description="研究中心显示名称字段。",
    ),
    "SUBJID": DeterministicMetadataDecision(
        rule_id="exact_subject_identifier",
        recommended_role="subject_identifier",
        rule_description="项目内受试者标识字段。",
    ),
    "SUBJINI": DeterministicMetadataDecision(
        rule_id="exact_subject_initials",
        recommended_role="subject_initials",
        rule_description="EDC 导出中的受试者姓名缩写字段。",
    ),
    "USUBJID": DeterministicMetadataDecision(
        rule_id="exact_unique_subject_identifier",
        recommended_role="subject_identifier",
        rule_description="跨域唯一受试者标识字段。",
    ),
    "__SUBJECTKEY": DeterministicMetadataDecision(
        rule_id="exact_odm_subject_key",
        recommended_role="subject_identifier",
        rule_description="ODM 受试者键字段。",
    ),
    "VISTOID": DeterministicMetadataDecision(
        rule_id="exact_visit_oid",
        recommended_role="visit_identifier",
        rule_description="EDC 访视对象标识字段。",
    ),
    "VISIT": DeterministicMetadataDecision(
        rule_id="exact_visit_name",
        recommended_role="visit_name",
        rule_description="EDC 访视显示名称字段。",
    ),
    "VISITNUM": DeterministicMetadataDecision(
        rule_id="exact_visit_sequence_number",
        recommended_role="visit_sequence_number",
        rule_description="EDC 访视计划顺序字段。",
    ),
    "__STUDYEVENTOID": DeterministicMetadataDecision(
        rule_id="exact_odm_study_event_oid",
        recommended_role="visit_identifier",
        rule_description="ODM 研究事件或访视对象标识字段。",
    ),
    "VISTREP": DeterministicMetadataDecision(
        rule_id="exact_visit_repeat_key",
        recommended_role="visit_repeat_key",
        rule_description="EDC 访视重复实例键字段。",
    ),
    "__STUDYEVENTREPEATKEY": DeterministicMetadataDecision(
        rule_id="exact_odm_study_event_repeat_key",
        recommended_role="visit_repeat_key",
        rule_description="ODM 研究事件重复实例键字段。",
    ),
    "FORMOID": DeterministicMetadataDecision(
        rule_id="exact_form_oid",
        recommended_role="form_identifier",
        rule_description="EDC 表单对象标识字段。",
    ),
    "__FORMOID": DeterministicMetadataDecision(
        rule_id="exact_odm_form_oid",
        recommended_role="form_identifier",
        rule_description="ODM 表单对象标识字段。",
    ),
    "FORMREP": DeterministicMetadataDecision(
        rule_id="exact_form_repeat_key",
        recommended_role="form_repeat_key",
        rule_description="EDC 表单重复实例键字段。",
    ),
    "__FORMREPEATKEY": DeterministicMetadataDecision(
        rule_id="exact_odm_form_repeat_key",
        recommended_role="form_repeat_key",
        rule_description="ODM 表单重复实例键字段。",
    ),
    "__ITEMGROUPOID": DeterministicMetadataDecision(
        rule_id="exact_odm_item_group_oid",
        recommended_role="item_group_identifier",
        rule_description="ODM 条目组对象标识字段。",
    ),
    "RECREP": DeterministicMetadataDecision(
        rule_id="exact_record_repeat_key",
        recommended_role="record_repeat_key",
        rule_description="EDC 重复记录实例键字段。",
    ),
    "CRFVER": DeterministicMetadataDecision(
        rule_id="exact_crf_version",
        recommended_role="crf_version",
        rule_description="EDC 表单或 CRF 版本字段。",
    ),
    "FORMNM": DeterministicMetadataDecision(
        rule_id="exact_form_name",
        recommended_role="form_name",
        rule_description="EDC 表单显示名称字段。",
    ),
    "GROUPID": DeterministicMetadataDecision(
        rule_id="exact_record_group_identifier",
        recommended_role="record_group_identifier",
        rule_description=(
            "来源 EDC 的记录组标识字段；不据此声称为 ODM ItemGroupOID。"
        ),
    ),
    "BLOCK顺序号": DeterministicMetadataDecision(
        rule_id="exact_export_block_sequence",
        recommended_role="record_block_sequence",
        rule_description="EDC 导出中的表单块或重复记录显示顺序字段。",
    ),
    "ISDEL": DeterministicMetadataDecision(
        rule_id="exact_record_deletion_flag",
        recommended_role="record_deletion_flag",
        rule_description="EDC 记录删除状态字段。",
    ),
    "PAGEFSDT": DeterministicMetadataDecision(
        rule_id="exact_page_first_saved_datetime",
        recommended_role="page_first_saved_datetime",
        rule_description="EDC 页面首次保存时间字段。",
    ),
    "PAGELMBY": DeterministicMetadataDecision(
        rule_id="exact_page_last_modified_by",
        recommended_role="page_last_modified_by",
        rule_description="EDC 页面最后修改人员字段。",
    ),
    "PAGELMDT": DeterministicMetadataDecision(
        rule_id="exact_page_last_modified_datetime",
        recommended_role="page_last_modified_datetime",
        rule_description="EDC 页面最后修改时间字段。",
    ),
    "PSTUDYID": DeterministicMetadataDecision(
        rule_id="exact_parent_study_identifier",
        recommended_role="study_identifier",
        rule_description="项目来源中的研究标识字段。",
    ),
    "PSTUDYNM": DeterministicMetadataDecision(
        rule_id="exact_parent_study_name",
        recommended_role="study_name",
        rule_description="项目来源中的研究名称字段。",
    ),
}


def deterministic_metadata_decision(
    domain: str,
    source_field: str,
) -> Optional[DeterministicMetadataDecision]:
    del domain
    normalized = str(source_field).strip().upper()
    exact = _EXACT_FIELD_RULES.get(normalized)
    if exact is not None:
        return exact
    if _DUPLICATE_FORM_NAME_RE.fullmatch(normalized):
        return DeterministicMetadataDecision(
            rule_id="duplicate_export_form_name",
            recommended_role="form_name_duplicate",
            rule_description=(
                "解析器为同一来源表中的重复表单名称列添加序号后缀；"
                "保留为次级技术定位字段。"
            ),
        )
    if _DOUBLE_UNDERSCORE_OID_RE.fullmatch(normalized):
        return DeterministicMetadataDecision(
            rule_id="double_underscore_oid_suffix",
            recommended_role="edc_object_identifier",
            rule_description=(
                "双下划线前缀且以 OID 结尾的 EDC/ODM 技术对象标识字段。"
            ),
        )
    if _DOUBLE_UNDERSCORE_REPEAT_KEY_RE.fullmatch(normalized):
        return DeterministicMetadataDecision(
            rule_id="double_underscore_repeat_key_suffix",
            recommended_role="edc_repeat_key",
            rule_description=(
                "双下划线前缀且以 REPEATKEY 结尾的 EDC/ODM 重复实例键字段。"
            ),
        )
    return None


def partition_metadata_fields(
    fields: Sequence[Mapping[str, Any]],
) -> Tuple[
    tuple[tuple[Mapping[str, Any], DeterministicMetadataDecision], ...],
    tuple[Mapping[str, Any], ...],
]:
    deterministic = []
    remaining = []
    for field in fields:
        decision = deterministic_metadata_decision(
            str(field.get("domain", "")),
            str(field.get("field", "")),
        )
        if decision is None:
            remaining.append(field)
        else:
            deterministic.append((field, decision))
    return tuple(deterministic), tuple(remaining)


def deterministic_metadata_mappings(
    fields: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    deterministic, _ = partition_metadata_fields(fields)
    return tuple(
        decision.mapping(
            domain=str(field["domain"]).strip(),
            source_field=str(field["field"]).strip(),
        )
        for field, decision in deterministic
    )


def deterministic_metadata_provenance(
    fields: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], ...]:
    deterministic, _ = partition_metadata_fields(fields)
    return tuple(
        decision.provenance(
            domain=str(field["domain"]).strip(),
            source_field=str(field["field"]).strip(),
        )
        for field, decision in deterministic
    )
