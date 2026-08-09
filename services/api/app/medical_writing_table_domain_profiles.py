from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from packages.contracts.workbench_contracts import StructuredTable, StructuredTableDomain


@dataclass(frozen=True)
class DomainColumnRole:
    role_id: str
    label: str
    description: str
    required: bool = False
    control: str = "text"
    options: tuple[str, ...] = ()
    allow_custom: bool = True

    def catalog_item(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "control": self.control,
            "options": list(self.options),
            "allow_custom": self.allow_custom,
        }


@dataclass(frozen=True)
class MedicalWritingTableDomainProfile:
    profile_id: str
    version: str
    domain: StructuredTableDomain
    label: str
    evidence_grade: str
    designer_status: str
    purpose: str
    column_roles: tuple[DomainColumnRole, ...]
    default_column_roles: tuple[str, ...]
    warning_text: str = ""

    def catalog_item(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "domain": self.domain.value,
            "label": self.label,
            "evidence_grade": self.evidence_grade,
            "designer_status": self.designer_status,
            "purpose": self.purpose,
            "column_roles": [role.catalog_item() for role in self.column_roles],
            "warning_text": self.warning_text,
        }


PROFILES: tuple[MedicalWritingTableDomainProfile, ...] = (
    MedicalWritingTableDomainProfile(
        profile_id="objectives_endpoints",
        version="1.0",
        domain=StructuredTableDomain.OBJECTIVES_ENDPOINTS,
        label="研究目的与终点",
        evidence_grade="A",
        designer_status="promoted",
        purpose="建立目的、终点、评价时间窗、分析集和估计目标之间的可追溯关系。",
        column_roles=(
            DomainColumnRole(
                "hierarchy",
                "终点层级",
                "主要、共同主要、关键次要、次要或探索性层级。",
                True,
                "suggest",
                ("主要", "共同主要", "关键次要", "次要", "探索性"),
            ),
            DomainColumnRole("objective_text", "研究目的", "当前层级的研究目的。", True),
            DomainColumnRole("endpoint_text", "对应终点", "与研究目的对应的终点定义。", True),
            DomainColumnRole("assessment_window", "评价时间窗", "终点评价时点、期间或时间窗。"),
            DomainColumnRole("analysis_population", "分析集", "用于该终点的分析人群或分析集。"),
            DomainColumnRole("estimand_notes", "估计目标/备注", "估计目标、事件处理或其他说明。"),
        ),
        default_column_roles=(
            "hierarchy",
            "objective_text",
            "endpoint_text",
            "assessment_window",
            "analysis_population",
            "estimand_notes",
        ),
    ),
    MedicalWritingTableDomainProfile(
        profile_id="sample_size_assumptions",
        version="1.0",
        domain=StructuredTableDomain.SAMPLE_SIZE_ASSUMPTIONS,
        label="样本量估算假设",
        evidence_grade="A",
        designer_status="promoted",
        purpose="按参数或情景组织样本量估算假设、依据和敏感性分析，不绑定项目公式。",
        column_roles=(
            DomainColumnRole("parameter", "参数/情景", "估算参数、终点、比较或分析情景。", True),
            DomainColumnRole("base_assumption", "基本假设/取值", "当前项目采用的假设值或参数值。", True),
            DomainColumnRole("source_basis", "依据/来源", "方案内依据、文献、历史数据或统计说明。"),
            DomainColumnRole("sensitivity_scenario", "敏感性情景", "备选参数、范围或敏感性分析情景。"),
            DomainColumnRole("pending_confirmation", "待确认项", "尚待统计、医学或项目团队确认的事项。"),
            DomainColumnRole("effect_or_margin", "效应量/界值", "效应量、非劣界值或优效性差异。"),
            DomainColumnRole("alpha_power", "检验水准/把握度", "单侧或双侧检验水准及目标把握度。"),
            DomainColumnRole("allocation_dropout", "分配比/脱落率", "组间分配和脱落、不可评价或调整假设。"),
            DomainColumnRole("estimated_sample_size", "估算样本量", "基础或调整后的样本量结果。"),
            DomainColumnRole("method_software", "方法/软件", "估算方法、模拟方法或软件及版本。"),
        ),
        default_column_roles=(
            "parameter",
            "base_assumption",
            "source_basis",
            "sensitivity_scenario",
            "pending_confirmation",
        ),
        warning_text="模板只提供参数矩阵结构，不执行或替代项目统计计算；公式、算法和数值必须来自当前项目并经统计与医学确认。",
    ),
    MedicalWritingTableDomainProfile(
        profile_id="treatment_dose",
        version="1.0",
        domain=StructuredTableDomain.TREATMENT_DOSE,
        label="试验用药与给药方案",
        evidence_grade="A",
        designer_status="promoted",
        purpose="区分治疗组、试验用药/对照、规格、剂量频次、途径、治疗期和依从性要求。",
        column_roles=(
            DomainColumnRole("treatment_arm", "治疗组", "治疗组、队列或剂量组标识。", True),
            DomainColumnRole("study_product", "试验用药/对照", "试验用药、安慰剂或阳性对照。", True),
            DomainColumnRole("dosage_form_strength", "剂型与规格", "剂型、规格和包装信息。"),
            DomainColumnRole("dose_frequency", "剂量与频次", "给药量、频次及必要的剂量说明。", True),
            DomainColumnRole(
                "administration_route",
                "给药途径",
                "给药途径；选项仅用于快速录入。",
                False,
                "suggest",
                ("口服", "外用", "皮下注射", "静脉输注", "肌内注射", "吸入"),
            ),
            DomainColumnRole("treatment_period", "治疗期", "给药阶段、周期或持续时间。"),
            DomainColumnRole("adherence_requirement", "依从性要求", "给药依从性计算、记录或处置要求。"),
        ),
        default_column_roles=(
            "treatment_arm",
            "study_product",
            "dosage_form_strength",
            "dose_frequency",
            "administration_route",
            "treatment_period",
            "adherence_requirement",
        ),
    ),
    MedicalWritingTableDomainProfile(
        profile_id="dose_modification",
        version="1.0",
        domain=StructuredTableDomain.DOSE_MODIFICATION,
        label="试验用药剂量调整与变更",
        evidence_grade="B",
        designer_status="guarded",
        purpose="单列试验用药暂停、减量、恢复、永久停药和其他治疗变更规则。",
        column_roles=(
            DomainColumnRole(
                "trigger_condition",
                "触发条件",
                "触发试验用药处置的事件或检查结果。",
                True,
                "suggest",
                ("实验室检查异常", "不良事件/耐受性", "依从性", "方案规定的其他情形"),
            ),
            DomainColumnRole("severity_threshold", "严重程度/阈值", "仅录入当前项目方案或医学确认的等级、阈值。"),
            DomainColumnRole(
                "study_product_action",
                "试验用药处置",
                "继续、暂停、减量、恢复、永久停药或其他当前方案规定处置。",
                True,
                "suggest",
                ("继续用药", "暂停用药", "减量", "恢复用药", "永久停药", "其他方案规定处置"),
            ),
            DomainColumnRole("retest_recovery", "复测与恢复条件", "复测时间、频次和恢复用药条件。"),
            DomainColumnRole("permanent_discontinuation", "永久停药条件", "当前项目规定的永久停药边界。"),
            DomainColumnRole("record_reporting", "记录与报告", "记录、随访和报告要求。"),
        ),
        default_column_roles=(
            "trigger_condition",
            "severity_threshold",
            "study_product_action",
            "retest_recovery",
            "permanent_discontinuation",
            "record_reporting",
        ),
        warning_text="这是试验用药处置，不是合并用药（CM）。本设计器不内置任何项目阈值；阈值和处置必须来自当前项目方案或医学确认。",
    ),
    MedicalWritingTableDomainProfile(
        profile_id="laboratory_panel",
        version="1.0",
        domain=StructuredTableDomain.LABORATORY_PANEL,
        label="实验室检查项目",
        evidence_grade="A",
        designer_status="promoted",
        purpose="模块化组织检查组合、具体项目、标本准备、参考范围、访视和复测规则。",
        column_roles=(
            DomainColumnRole(
                "panel",
                "检查组合",
                "检查组合；选项仅作为跨项目通用起点。",
                True,
                "suggest",
                ("血常规", "血生化", "尿常规", "凝血功能", "妊娠检查", "其他"),
            ),
            DomainColumnRole("analyte", "具体项目", "该组合包含的具体分析物或检查项目。", True),
            DomainColumnRole("specimen_preparation", "标本/准备", "标本类型、空腹要求和采集前准备。"),
            DomainColumnRole("unit_reference_range", "单位/参考范围", "单位、参考范围或中心实验室说明。"),
            DomainColumnRole("collection_visit", "采集访视", "采集访视、研究日或条件。"),
            DomainColumnRole("abnormality_retest_rule", "异常与复测规则", "异常判定、复测与随访要求。"),
        ),
        default_column_roles=(
            "panel",
            "analyte",
            "specimen_preparation",
            "unit_reference_range",
            "collection_visit",
            "abnormality_retest_rule",
        ),
    ),
    MedicalWritingTableDomainProfile(
        profile_id="pk_immunogenicity_schedule",
        version="1.0",
        domain=StructuredTableDomain.PK_IMMUNOGENICITY_SCHEDULE,
        label="PK/PD/免疫原性采样计划",
        evidence_grade="A",
        designer_status="promoted",
        purpose="组织PK、PD、免疫原性和相关生物分析采样的访视、给药锚点、样本与处理要求。",
        column_roles=(
            DomainColumnRole("assessment_type", "评估类型", "PK、PD、免疫原性或当前项目规定的其他类型。"),
            DomainColumnRole("cohort_period", "队列/治疗期", "队列、治疗组、周期或研究阶段。"),
            DomainColumnRole("sampling_timepoint", "访视/研究日/时点", "访视、研究周、研究日或名义采样时点。"),
            DomainColumnRole("dose_relation", "相对给药时间", "给药前、给药后或相对给药的名义时间。"),
            DomainColumnRole("allowable_window", "允许时间窗", "采样允许窗及优先级规则。"),
            DomainColumnRole("analyte", "分析物/检测目标", "药物、ADA、PD指标或其他当前项目分析物。"),
            DomainColumnRole("specimen_matrix", "样本类型/基质", "血清、血浆、全血、尿液、组织或其他基质。"),
            DomainColumnRole("planned_marker", "计划标记", "计划采集标记、次数或矩阵单元格状态。"),
            DomainColumnRole("sample_reference_id", "样本编号", "样本参考编号、采样管或实验室编号规则。"),
            DomainColumnRole("sample_volume", "样本量", "单次采样量、分装量或累计样本负担。"),
            DomainColumnRole("handling_storage_shipping", "处理/保存/运输", "离心、分装、保存温度、运输和时限。"),
            DomainColumnRole("method_lab", "方法/实验室", "检测方法、中心实验室或生物分析实验室。"),
            DomainColumnRole("actual_time_capture", "实际时间记录", "实际给药、采样、处理或接收时间的记录要求。"),
            DomainColumnRole("conditional_trigger", "条件触发", "提前终止、剂量调整、安全事件或其他额外采样条件。"),
        ),
        default_column_roles=(
            "assessment_type",
            "sampling_timepoint",
            "dose_relation",
            "allowable_window",
            "specimen_matrix",
            "handling_storage_shipping",
            "actual_time_capture",
        ),
        warning_text="来源表可采用访视行、密集时点矩阵或按分析物分列；建立语义映射时不得强制压成固定列数或复制其他项目时点。",
    ),
    MedicalWritingTableDomainProfile(
        profile_id="analysis_sets",
        version="1.0",
        domain=StructuredTableDomain.ANALYSIS_SETS,
        label="分析集定义",
        evidence_grade="A",
        designer_status="promoted",
        purpose="保留分析集名称与定义的来源忠实核心，并按需补充纳入、排除、用途和偏离处理。",
        column_roles=(
            DomainColumnRole("set_name", "分析集", "分析集或分析人群名称。", True),
            DomainColumnRole("definition", "定义", "当前项目对该分析集的完整定义。", True),
            DomainColumnRole("inclusion_rule", "纳入规则", "可从定义中明确拆分且有来源支持的纳入条件。"),
            DomainColumnRole("exclusion_rule", "排除规则", "可从定义中明确拆分且有来源支持的排除条件。"),
            DomainColumnRole("primary_use", "主要用途", "疗效、安全性、PK、PD、免疫原性或其他分析用途。"),
            DomainColumnRole("deviation_sensitivity_handling", "偏离/敏感性处理", "方案偏离、实际治疗分组或敏感性分析处理。"),
            DomainColumnRole("region_subpopulation", "区域/亚组", "中国、日本或其他区域和预设亚组变体。"),
        ),
        default_column_roles=(
            "set_name",
            "definition",
            "inclusion_rule",
            "exclusion_rule",
            "primary_use",
            "deviation_sensitivity_handling",
        ),
        warning_text="新建表提供FAS、PPS和SS的项目无关标准起草文本，全部保持待项目确认；原始方案若仅有“分析集—定义”两列，应保持原结构，具体纳入、排除、用途和偏离处理必须按当前方案/SAP修订。",
    ),
    MedicalWritingTableDomainProfile(
        profile_id="version_history",
        version="1.0",
        domain=StructuredTableDomain.VERSION_HISTORY,
        label="文件版本历史",
        evidence_grade="A",
        designer_status="promoted",
        purpose="记录版本、日期、变更范围、变更摘要、变更理由和批准状态。",
        column_roles=(
            DomainColumnRole("version_label", "版本", "文件版本号或版本标签。", True),
            DomainColumnRole("version_date", "日期", "版本日期；由用户输入或确认。", True, "date"),
            DomainColumnRole("change_scope", "变更章节/范围", "本版本涉及的章节或范围。"),
            DomainColumnRole("change_summary", "变更摘要", "本版本的主要变更。", True),
            DomainColumnRole("change_reason", "变更理由", "变更原因或决策依据。"),
            DomainColumnRole(
                "approval_status",
                "批准状态",
                "仅记录人工确认的文件状态，系统不自动推断。",
                False,
                "suggest",
                ("草案", "内部审阅中", "医学已批准", "已替代"),
            ),
        ),
        default_column_roles=(
            "version_label",
            "version_date",
            "change_scope",
            "change_summary",
            "change_reason",
            "approval_status",
        ),
        warning_text="批准状态必须由有权限的用户明确确认，系统不会根据版本号或日期自动推断。",
    ),
)


class MedicalWritingTableDomainProfileService:
    def __init__(
        self,
        profiles: Iterable[MedicalWritingTableDomainProfile] = PROFILES,
    ):
        self._profiles = {profile.domain.value: profile for profile in profiles}

    def catalog(self) -> list[dict[str, Any]]:
        return [profile.catalog_item() for profile in self._profiles.values()]

    def for_domain(
        self, domain: StructuredTableDomain | str
    ) -> MedicalWritingTableDomainProfile | None:
        value = domain.value if isinstance(domain, StructuredTableDomain) else str(domain)
        return self._profiles.get(value)

    def template_state(self, domain: StructuredTableDomain | str) -> dict[str, Any]:
        profile = self.for_domain(domain)
        if profile is None:
            return {}
        return {
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "mapping_status": "template_roles_attached",
            "confirmed_by_user": False,
            "record_axis": "rows",
            "source": "medical_writing_template",
        }

    def validate(self, table: StructuredTable) -> list[dict[str, str]]:
        profile = self.for_domain(table.domain)
        if profile is None:
            return []
        findings: list[dict[str, str]] = []
        allowed_roles = {role.role_id for role in profile.column_roles}
        present_roles = {column.semantic_role for column in table.columns if column.semantic_role}
        for role in sorted(present_roles - allowed_roles):
            findings.append(
                {
                    "severity": "error",
                    "code": "unknown_semantic_role",
                    "message": f"领域 {profile.label} 不支持语义角色 {role}",
                }
            )
        for role in profile.column_roles:
            if role.required and role.role_id not in present_roles:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "required_role_unmapped",
                        "message": f"尚未映射必需字段：{role.label}",
                    }
                )

        state = table.word_layout.get("domain_profile")
        if state is not None and not isinstance(state, dict):
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_profile_state",
                    "message": "领域 profile 状态必须是对象",
                }
            )
            return findings
        state = state or {}
        profile_id = str(state.get("profile_id") or "")
        if profile_id and profile_id != profile.profile_id:
            findings.append(
                {
                    "severity": "error",
                    "code": "profile_domain_mismatch",
                    "message": f"领域 profile {profile_id} 与表格领域 {profile.domain.value} 不一致",
                }
            )
        mapping_status = str(state.get("mapping_status") or "pending_user_confirmation")
        if mapping_status not in {
            "template_roles_attached",
            "pending_user_confirmation",
            "confirmed_by_user",
        }:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_mapping_status",
                    "message": f"未知领域映射状态：{mapping_status}",
                }
            )
        confirmed_by_user = state.get("confirmed_by_user", False)
        if not isinstance(confirmed_by_user, bool):
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_confirmation_state",
                    "message": "领域映射确认状态必须是布尔值",
                }
            )
        elif mapping_status == "confirmed_by_user" and not confirmed_by_user:
            findings.append(
                {
                    "severity": "error",
                    "code": "inconsistent_confirmation_state",
                    "message": "领域映射状态与确认标记不一致",
                }
            )
        record_axis = str(state.get("record_axis") or "semantic_only")
        if record_axis not in {"rows", "semantic_only"}:
            findings.append(
                {
                    "severity": "error",
                    "code": "invalid_record_axis",
                    "message": f"未知记录方向：{record_axis}",
                }
            )
        if mapping_status == "pending_user_confirmation" or (
            mapping_status == "template_roles_attached"
            and not bool(state.get("confirmed_by_user"))
        ):
            findings.append(
                {
                    "severity": "warning",
                    "code": "mapping_pending",
                    "message": "领域语义映射尚待医学用户确认",
                }
            )
        if record_axis == "rows":
            role_columns: dict[str, list[str]] = {}
            for column in table.columns:
                if column.semantic_role:
                    role_columns.setdefault(column.semantic_role, []).append(column.column_id)
            required_roles = [role for role in profile.column_roles if role.required]
            for row in table.rows[table.header_row_count :]:
                cell_text = {cell.column_id: str(cell.text or "").strip() for cell in row.cells}
                if not any(cell_text.values()):
                    continue
                for role in required_roles:
                    column_ids = role_columns.get(role.role_id, [])
                    if column_ids and any(cell_text.get(column_id, "") for column_id in column_ids):
                        continue
                    findings.append(
                        {
                            "severity": "warning",
                            "code": "required_cell_empty",
                            "finding_key": f"{row.row_id}:{role.role_id}",
                            "message": f"第 {row.order + 1} 行缺少必需内容：{role.label}",
                        }
                    )
        if profile.designer_status == "guarded" and not bool(
            state.get("project_evidence_confirmed_by_user")
        ):
            findings.append(
                {
                    "severity": "warning",
                    "code": "project_evidence_required",
                    "message": profile.warning_text,
                }
            )
        return findings

    def assert_valid(self, table: StructuredTable) -> None:
        errors = [item for item in self.validate(table) if item["severity"] == "error"]
        if errors:
            raise ValueError("；".join(item["message"] for item in errors))
