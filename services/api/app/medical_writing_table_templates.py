from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    ApprovalState,
    StructuredTable,
    StructuredTableCell,
    StructuredTableColumn,
    StructuredTableDomain,
    StructuredTableRole,
    StructuredTableRow,
)

from .medical_writing_tables import MedicalWritingTableService
from .medical_writing_design_projection import normalize_study_design
from .medical_writing_table_domain_profiles import (
    MedicalWritingTableDomainProfileService,
)

# Templates whose instantiate path is design-sensitive and must consume the
# confirmed ProtocolAssemblyPlan ``soa`` projection (研究流程表 only).
_SOA_PLAN_GATED_TEMPLATE_IDS = frozenset({"schedule_of_activities"})


@dataclass(frozen=True)
class MedicalWritingTableTemplate:
    template_id: str
    label: str
    domain: StructuredTableDomain
    purpose: str
    designer_kind: str
    columns: tuple[str, ...]
    starter_rows: tuple[tuple[str, ...], ...]
    recommended_note_types: tuple[str, ...] = ()
    orientation: str = "landscape"
    supports_custom_dimensions: bool = False

    def catalog_item(self) -> Dict[str, object]:
        return {
            "template_id": self.template_id,
            "label": self.label,
            "domain": self.domain.value,
            "purpose": self.purpose,
            "designer_kind": self.designer_kind,
            "columns": list(self.columns),
            "starter_row_count": len(self.starter_rows),
            "recommended_note_types": list(self.recommended_note_types),
            "orientation": self.orientation,
            "supports_custom_dimensions": self.supports_custom_dimensions,
        }


TEMPLATES: tuple[MedicalWritingTableTemplate, ...] = (
    MedicalWritingTableTemplate(
        "schedule_of_activities",
        "研究流程表",
        StructuredTableDomain.SCHEDULE_OF_ACTIVITIES,
        "模块化编排研究阶段、访视、研究日/时间窗、活动及表下注释。",
        "schedule_of_activities",
        ("研究活动", "筛选期", "基线/随机", "治疗期访视", "随访"),
        (
            ("知情同意", "", "", "", ""),
            ("入排标准", "", "", "", ""),
            ("疗效评估", "", "", "", ""),
            ("安全性评估", "", "", "", ""),
            ("试验用药", "", "", "", ""),
        ),
        ("item_set", "timing_rule", "condition", "exception", "operational"),
    ),
    MedicalWritingTableTemplate(
        "objectives_endpoints",
        "研究目的与终点",
        StructuredTableDomain.OBJECTIVES_ENDPOINTS,
        "建立目的、对应终点、评价时间窗和分析集之间的可追溯对应关系。",
        "objectives_endpoints",
        ("层级", "研究目的", "对应终点", "评价时间窗", "分析集", "估计目标/备注"),
        (
            ("主要", "", "", "", "", ""),
            ("关键次要", "", "", "", "", ""),
            ("其他次要/探索性", "", "", "", "", ""),
        ),
        ("definition", "timing_rule", "condition"),
    ),
    MedicalWritingTableTemplate(
        "sample_size_assumptions",
        "样本量估算假设",
        StructuredTableDomain.SAMPLE_SIZE_ASSUMPTIONS,
        "并列呈现效应量、变异、检验水准、把握度、脱落率和敏感性假设。",
        "assumption_matrix",
        ("参数", "基本假设", "依据/来源", "敏感性情景", "待确认项"),
        (
            ("主要终点效应量", "", "", "", ""),
            ("变异/事件率", "", "", "", ""),
            ("检验水准与把握度", "", "", "", ""),
            ("脱落/不可评价比例", "", "", "", ""),
        ),
        ("definition", "condition"),
        "portrait",
    ),
    MedicalWritingTableTemplate(
        "treatment_dose",
        "试验用药与给药方案",
        StructuredTableDomain.TREATMENT_DOSE,
        "区分试验药物、对照、给药途径、剂量频次、治疗期和依从性要求。",
        "treatment_dose",
        ("治疗组", "试验用药/对照", "剂型与规格", "剂量与频次", "给药途径", "治疗期", "依从性要求"),
        (("组 1", "", "", "", "", "", ""), ("组 2", "", "", "", "", "", "")),
        ("condition", "operational"),
    ),
    MedicalWritingTableTemplate(
        "dose_modification",
        "试验用药剂量调整与变更",
        StructuredTableDomain.DOSE_MODIFICATION,
        "单列试验用药暂停、减量、恢复、永久停药和其他治疗变更规则；不与CM混用。",
        "dose_modification",
        ("触发条件", "严重程度/阈值", "试验用药处置", "复测与恢复条件", "永久停药条件", "记录与报告"),
        (
            ("实验室异常", "", "", "", "", ""),
            ("不良事件/耐受性", "", "", "", "", ""),
            ("其他方案规定情形", "", "", "", "", ""),
        ),
        ("condition", "timing_rule", "exception", "operational"),
    ),
    MedicalWritingTableTemplate(
        "stopping_rules",
        "暂停与停止规则",
        StructuredTableDomain.STOPPING_RULES,
        "分层定义个体、队列/剂量组、中心和整体研究的暂停或停止边界。",
        "stopping_rules",
        ("适用层级", "触发事件", "判定阈值", "即时处置", "复核主体", "恢复/终止条件"),
        (
            ("受试者", "", "", "", "", ""),
            ("队列/剂量组", "", "", "", "", ""),
            ("整个研究", "", "", "", "", ""),
        ),
        ("condition", "exception", "operational"),
    ),
    MedicalWritingTableTemplate(
        "ae_management",
        "安全性事件管理",
        StructuredTableDomain.AE_MANAGEMENT,
        "结构化定义AE、SAE、AESI等事件的识别、评估、随访和报告要求。",
        "safety_event_management",
        ("事件类别", "识别/判定标准", "严重程度与因果性", "随访要求", "报告时限", "试验用药处置", "责任角色"),
        (
            ("AE", "", "", "", "", "", ""),
            ("SAE", "", "", "", "", "", ""),
            ("AESI", "", "", "", "", "", ""),
        ),
        ("definition", "timing_rule", "condition", "operational"),
    ),
    MedicalWritingTableTemplate(
        "laboratory_panel",
        "实验室检查项目",
        StructuredTableDomain.LABORATORY_PANEL,
        "把检查组合、具体分析物、标本、单位、临床意义判定和复测规则拆成可复用模块。",
        "laboratory_panel",
        ("检查组合", "具体项目", "标本/准备", "单位/参考范围", "采集访视", "异常与复测规则"),
        (
            ("血常规", "", "", "", "", ""),
            ("血生化", "", "", "", "", ""),
            ("尿常规", "", "", "", "", ""),
            ("其他", "", "", "", "", ""),
        ),
        ("item_set", "specimen_preparation", "timing_rule", "condition"),
    ),
    MedicalWritingTableTemplate(
        "pk_immunogenicity_schedule",
        "PK/PD/免疫原性采样计划",
        StructuredTableDomain.PK_IMMUNOGENICITY_SCHEDULE,
        "同步呈现PK、PD、免疫原性采样的访视、给药锚点、允许时间窗、样本处理和实际时间记录要求。",
        "pk_immunogenicity_schedule",
        ("评估类型", "访视/研究日", "相对给药时间", "允许时间窗", "样本类型", "处理与保存", "实际时间记录"),
        (
            ("PK", "", "", "", "", "", ""),
            ("PD", "", "", "", "", "", ""),
            ("免疫原性", "", "", "", "", "", ""),
        ),
        ("timing_rule", "specimen_preparation", "condition"),
    ),
    MedicalWritingTableTemplate(
        "analysis_sets",
        "分析集定义",
        StructuredTableDomain.ANALYSIS_SETS,
        "明确分析集定义、纳入/排除规则、用途和偏离处理边界。",
        "analysis_sets",
        ("分析集", "定义", "纳入规则", "排除规则", "主要用途", "偏离/敏感性处理"),
        (
            (
                "全分析集（FAS）",
                "通常包括所有随机化且至少接受1次试验干预的受试者；具体定义以本研究方案和SAP为准。",
                "随机化并至少接受1次试验干预；是否要求基线后有效性评价需按项目确认。",
                "不因方案偏离或结局缺失事后排除；例外情形仅按方案和SAP预先规定执行。",
                "主要及次要有效性分析。",
                "通常按随机分组分析；缺失数据、治疗中止和重大方案偏离按估计目标及SAP预设方法处理。",
            ),
            (
                "符合方案集（PPS）",
                "全分析集中充分遵守方案且无影响主要疗效评价的重大方案偏离的受试者；具体定义以本研究方案和SAP为准。",
                "属于全分析集，并达到方案和SAP预先规定的主要疗效可评价要求。",
                "排除对主要疗效评价产生重要影响的重大方案偏离；排除规则须在盲态数据审核前确定。",
                "主要有效性分析的支持性或敏感性分析。",
                "不得依据治疗结果事后排除受试者；具体重大方案偏离清单由盲态数据审核确认。",
            ),
            (
                "安全性集（SS）",
                "所有至少接受1次试验干预的受试者；具体暴露和分组规则以本研究方案和SAP为准。",
                "有任何试验干预暴露记录。",
                "无试验干预暴露记录。",
                "安全性、暴露量及依从性分析。",
                "原则上按实际接受的试验干预分组；暴露归属和交叉用药规则按SAP预先规定。",
            ),
        ),
        ("definition", "condition", "exception"),
        "portrait",
    ),
    MedicalWritingTableTemplate(
        "version_history",
        "文件版本历史",
        StructuredTableDomain.VERSION_HISTORY,
        "记录版本、日期、变更范围、变更理由和批准状态。",
        "version_history",
        ("版本", "日期", "变更章节/范围", "变更摘要", "变更理由", "批准状态"),
        (("", "", "", "", "", ""),),
        ("operational",),
        "portrait",
    ),
    MedicalWritingTableTemplate(
        "generic_table",
        "自定义结构化表格",
        StructuredTableDomain.GENERIC,
        "按当前方案章节需要自定义行列、表头、版式和附注区，插入后进入统一表格设计器。",
        "generic",
        ("列 1", "列 2", "列 3"),
        (("", "", ""), ("", "", ""), ("", "", ""), ("", "", "")),
        (),
        "auto",
        True,
    ),
)


def _soa_projection_matrix(
    definition: Any,
    design_projection: Any,
) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    """Project a reviewable SoA starter matrix from normalized design facts."""

    view = design_projection.design_view
    picos = definition.picos
    columns: list[str] = ["研究活动", "筛选期"]
    if view.phase1_parts:
        columns.extend(
            part.part_label or part.part_code for part in view.phase1_parts
        )
        columns.append("安全性随访")
    elif view.crossover.planned is True:
        columns.extend(view.crossover.periods)
        washout_label = view.crossover.washout_strategy or "洗脱期"
        if washout_label not in columns:
            columns.insert(min(3, len(columns)), washout_label)
        columns.append("随访")
    else:
        epochs = [
            str(item).strip()
            for item in (getattr(picos, "study_epochs", []) or [])
            if str(item).strip()
        ]
        if not epochs:
            epochs = ["基线/随机", "治疗期", "随访"]
        columns.extend(item for item in epochs if item not in columns)
        if view.treatment_switch.planned is True:
            switch_label = (
                view.treatment_switch.trigger_or_timing or "治疗切换"
            )
            if switch_label not in columns:
                columns.append(switch_label)
        if view.open_label_extension.planned is True:
            extension_label = (
                f"开放标签延展（{view.open_label_extension.duration}）"
                if view.open_label_extension.duration
                else "开放标签延展"
            )
            if extension_label not in columns:
                columns.append(extension_label)
    if view.interim_analysis.planned is True:
        interim_label = view.interim_analysis.timing or "期中分析时点"
        if interim_label not in columns:
            columns.append(interim_label)
    if view.adaptive_design.planned is True:
        adaptive_label = view.adaptive_design.adaptation_timing or "适应性决策时点"
        if adaptive_label not in columns:
            columns.append(adaptive_label)

    def row(label: str, values: dict[str, str] | None = None) -> tuple[str, ...]:
        payload = values or {}
        return tuple([label, *(payload.get(column, "") for column in columns[1:])])

    all_visits = {column: "X" for column in columns[1:]}
    rows: list[tuple[str, ...]] = [
        row("知情同意", {columns[1]: "X"}),
        row("入选/排除标准", {columns[1]: "X"}),
    ]
    if view.randomization_mode == "randomized":
        randomization_column = next(
            (
                column
                for column in columns[1:]
                if any(token in column for token in ("基线", "随机", "治疗"))
            ),
            columns[min(2, len(columns) - 1)],
        )
        rows.append(row("随机分配", {randomization_column: "X"}))
    rows.extend(
        [
            row(
                "研究干预",
                {
                    column: (
                        getattr(picos, "intervention_dose_regimen", "")
                        or getattr(picos, "intervention_summary", "")
                        or "X"
                    )
                    for column in columns[2:-1] or columns[2:]
                },
            ),
            row("疗效评估", dict(all_visits)),
            row("安全性评估", dict(all_visits)),
        ]
    )
    comparator = str(getattr(picos, "comparator_summary", "") or "").strip()
    if view.comparator_type in {"placebo", "active"}:
        rows.append(
            row(
                "安慰剂对照" if view.comparator_type == "placebo" else "阳性药对照",
                {
                    column: comparator or view.comparator_intervention or "X"
                    for column in columns[2:-1] or columns[2:]
                },
            )
        )
    background_rules = list(
        getattr(picos, "required_background_rules", []) or []
    )
    intervention_rules = getattr(picos, "intervention_rules", None)
    if intervention_rules is not None:
        background_rules.extend(
            str(getattr(item, "agent_or_category", "") or "").strip()
            for item in getattr(intervention_rules, "non_ip_treatment_rules", [])
            if str(getattr(item, "rule_class", "") or "").endswith("background")
        )
    background_rules = [item for item in background_rules if item]
    if background_rules:
        rows.append(
            row(
                "背景治疗",
                {
                    column: "；".join(background_rules)
                    for column in columns[2:-1] or columns[2:]
                },
            )
        )
    for part in view.phase1_parts:
        part_column = part.part_label or part.part_code
        detail = "；".join(
            item
            for item in (
                part.population,
                part.cohort_dose,
                part.soa_summary,
            )
            if item
        )
        rows.append(row(f"{part.part_code}队列/给药", {part_column: detail or "X"}))
        if part.pk_pd:
            rows.append(row(f"{part.part_code} PK/PD采样", {part_column: part.pk_pd}))
    if view.crossover.planned is True:
        rows.append(
            row(
                "交叉序列",
                {
                    column: "；".join(view.crossover.sequences)
                    for column in view.crossover.periods
                    if column in columns
                },
            )
        )
        washout_column = next(
            (column for column in columns if "洗脱" in column), ""
        )
        if washout_column:
            rows.append(
                row(
                    "洗脱及残留效应控制",
                    {washout_column: view.crossover.washout_strategy},
                )
            )
    if view.treatment_switch.planned is True:
        switch_column = next(
            (
                column
                for column in columns
                if column == view.treatment_switch.trigger_or_timing
            ),
            columns[-1],
        )
        rows.append(
            row(
                "治疗切换",
                {
                    switch_column: (
                        f"{view.treatment_switch.eligible_population}转入"
                        f"{view.treatment_switch.destination_treatment}"
                    )
                },
            )
        )
    if view.open_label_extension.planned is True:
        extension_column = next(
            (column for column in columns if "开放标签延展" in column),
            columns[-1],
        )
        rows.append(
            row(
                "开放标签延展",
                {
                    extension_column: (
                        f"{view.open_label_extension.entry_eligibility}；"
                        f"{view.open_label_extension.treatment_regimen}"
                    )
                },
            )
        )
    if view.interim_analysis.planned is True:
        interim_column = next(
            (
                column
                for column in columns
                if column == (view.interim_analysis.timing or "期中分析时点")
            ),
            columns[-1],
        )
        rows.append(
            row(
                "期中分析",
                {
                    interim_column: (
                        view.interim_analysis.purpose
                        or view.interim_analysis.information_fraction
                        or "X"
                    )
                },
            )
        )
    if view.sample_size_reestimation.planned is True:
        rows.append(
            row(
                "盲态样本量再估计"
                if view.sample_size_reestimation.reestimation_mode == "blinded"
                else "非盲态样本量再估计",
                {
                    columns[-1]: (
                        view.sample_size_reestimation.timing_or_information
                    )
                },
            )
        )
    if view.adaptive_design.planned is True:
        rows.append(
            row(
                "适应性决策",
                {
                    columns[-1]: (
                        f"{view.adaptive_design.adaptive_type}；"
                        f"{view.adaptive_design.decision_criteria}"
                    )
                },
            )
        )
    if view.src_planned is True:
        rows.append(row("SRC安全性审查", dict(all_visits)))
    if view.dmc_planned is True:
        rows.append(row("DMC数据监查", dict(all_visits)))
    return tuple(columns), rows


class MedicalWritingTableTemplateService:
    def __init__(
        self,
        templates: Iterable[MedicalWritingTableTemplate] = TEMPLATES,
        plan_consumption_helper: Any = None,
    ):
        self._templates = {item.template_id: item for item in templates}
        self._domain_profiles = MedicalWritingTableDomainProfileService()
        self._plan_helper = plan_consumption_helper

    def bind_plan_consumption_helper(self, plan_consumption_helper: Any) -> None:
        self._plan_helper = plan_consumption_helper

    def require_soa_plan_projection(
        self,
        *,
        project_id: str,
        template_id: str | None = None,
        domain: str | None = None,
    ) -> Any:
        """Gate design-sensitive SoA paths on the confirmed ``soa`` projection.

        Only ``schedule_of_activities`` / SCHEDULE_OF_ACTIVITIES is gated.
        Unrelated table templates remain ungated.
        """
        is_soa = False
        if template_id and template_id in _SOA_PLAN_GATED_TEMPLATE_IDS:
            is_soa = True
        domain_value = (domain or "").strip().lower()
        if domain_value in {
            StructuredTableDomain.SCHEDULE_OF_ACTIVITIES.value,
            "schedule_of_activities",
        }:
            is_soa = True
        if not is_soa:
            return None
        if self._plan_helper is None:
            # Production main.py always binds the helper. Unbound helper is only
            # for pure unit tests of non-plan table geometry.
            return None
        return self._plan_helper.require_confirmed_projection(
            project_id=project_id,
            projection_kind="soa",
        )

    def catalog(self) -> list[Dict[str, object]]:
        return [item.catalog_item() for item in self._templates.values()]

    def instantiate(
        self,
        template_id: str,
        *,
        title: str = "",
        instance_id: str = "",
        row_count: int | None = None,
        column_count: int | None = None,
        header_row_count: int | None = None,
        orientation: str = "",
        notes_area: bool = False,
        project_id: str = "",
        study_definition: Any = None,
    ) -> Dict[str, object]:
        template = self._templates.get(template_id)
        if template is None:
            raise KeyError(f"unknown medical-writing table template: {template_id}")
        plan_state = None
        design_projection = None
        resolved_definition = study_definition
        if template_id in _SOA_PLAN_GATED_TEMPLATE_IDS:
            if self._plan_helper is not None:
                plan_state, resolved_definition, design_projection = (
                    self._plan_helper.require_confirmed_design_projection(
                        project_id=project_id,
                        projection_kind="soa",
                    )
                )
            elif resolved_definition is not None:
                design_projection = normalize_study_design(resolved_definition)
            else:
                plan_state = self.require_soa_plan_projection(
                    project_id=project_id,
                    template_id=template_id,
                    domain=template.domain.value if template.domain else "",
                )
        else:
            plan_state = self.require_soa_plan_projection(
                project_id=project_id,
                template_id=template_id,
                domain=template.domain.value if template.domain else "",
            )
        custom_options_used = any(
            value is not None for value in (row_count, column_count, header_row_count)
        ) or bool(orientation) or notes_area
        if custom_options_used and not template.supports_custom_dimensions:
            raise ValueError(
                "custom rows, columns, headers, orientation and notes area are available only for generic_table"
            )
        if template.supports_custom_dimensions:
            total_rows = 5 if row_count is None else row_count
            total_columns = 3 if column_count is None else column_count
            header_rows = 1 if header_row_count is None else header_row_count
            if not isinstance(total_rows, int) or isinstance(total_rows, bool) or not 2 <= total_rows <= 50:
                raise ValueError("generic table row_count must be between 2 and 50")
            if not isinstance(total_columns, int) or isinstance(total_columns, bool) or not 2 <= total_columns <= 20:
                raise ValueError("generic table column_count must be between 2 and 20")
            if (
                not isinstance(header_rows, int)
                or isinstance(header_rows, bool)
                or header_rows < 0
                or header_rows >= total_rows
                or header_rows > 5
            ):
                raise ValueError(
                    "generic table header_row_count must be between 0 and 5 and smaller than row_count"
                )
            selected_orientation = orientation or template.orientation
            if selected_orientation not in {"auto", "portrait", "landscape"}:
                raise ValueError("generic table orientation must be auto, portrait or landscape")
            column_labels = tuple(f"列 {index + 1}" for index in range(total_columns))
            if header_rows:
                row_values = [column_labels]
                row_values.extend(tuple("" for _ in column_labels) for _ in range(header_rows - 1))
                row_values.extend(tuple("" for _ in column_labels) for _ in range(total_rows - header_rows))
            else:
                row_values = [tuple("" for _ in column_labels) for _ in range(total_rows)]
        else:
            if (
                template_id in _SOA_PLAN_GATED_TEMPLATE_IDS
                and resolved_definition is not None
                and design_projection is not None
            ):
                projected_columns, projected_rows = _soa_projection_matrix(
                    resolved_definition, design_projection
                )
                column_labels = projected_columns
                row_values = [projected_columns, *projected_rows]
            else:
                column_labels = template.columns
                row_values = [template.columns, *template.starter_rows]
            header_rows = 1
            selected_orientation = template.orientation
        token = _identifier_token(instance_id or uuid4().hex)
        profile = self._domain_profiles.for_domain(template.domain)
        block_id = f"mwgenerated_{token}_block"
        table_id = f"mwgenerated_{token}_table"
        source_locator = (
            f"generated:medical_writing_template:{template.template_id}:{token}"
        )
        columns = [
            StructuredTableColumn(
                column_id=f"mwgenerated_{token}_column_{column_index}",
                order=column_index,
                label=label,
                style_role="header",
                semantic_role=(
                    profile.default_column_roles[column_index]
                    if profile and column_index < len(profile.default_column_roles)
                    else ""
                ),
            )
            for column_index, label in enumerate(column_labels)
        ]
        rows = [
            _row(
                token,
                row_index,
                values,
                columns,
                header=row_index < header_rows,
            )
            for row_index, values in enumerate(row_values)
        ]
        table = StructuredTable(
            table_id=table_id,
            block_id=block_id,
            domain=template.domain,
            role=(
                StructuredTableRole.DOCUMENT_CONTROL
                if template.domain == StructuredTableDomain.VERSION_HISTORY
                else StructuredTableRole.BODY_CONTENT
            ),
            title=title.strip() or template.label,
            source_locator=source_locator,
            review_state=ApprovalState.AI_DRAFT,
            header_row_count=header_rows,
            columns=columns,
            rows=rows,
            notes=[],
            word_layout={
                "orientation": selected_orientation,
                "width_policy": "autofit",
                "notes_area_enabled": bool(notes_area),
                "split_strategy": "repeat_header",
                "frozen_column_count": 1,
                "template_id": template.template_id,
                "designer_kind": template.designer_kind,
                "recommended_note_types": list(template.recommended_note_types),
                **(
                    {"domain_profile": self._domain_profiles.template_state(template.domain)}
                    if profile
                    else {}
                ),
            },
        )
        block = MedicalWritingTableService().to_table_block(table)
        block.update(
            {
                "title": table.title,
                "source_kind": "medical_writing_template",
                "template_id": template.template_id,
                "template_instance_id": token,
                "editable": True,
            }
        )
        if plan_state is not None and getattr(plan_state, "plan", None) is not None:
            plan = plan_state.plan
            block["protocol_assembly_plan"] = {
                "plan_id": plan.plan_id,
                "plan_revision": plan.revision,
                "plan_sha256": plan.state_sha256,
                "projection": "soa",
            }
        return block


def _row(
    token: str,
    row_index: int,
    values: Sequence[str],
    columns: Sequence[StructuredTableColumn],
    *,
    header: bool,
) -> StructuredTableRow:
    row_id = f"mwgenerated_{token}_row_{row_index}"
    role = "header" if header else "body"
    return StructuredTableRow(
        row_id=row_id,
        order=row_index,
        label=str(values[0]) if values else "",
        style_role=role,
        cells=[
            StructuredTableCell(
                cell_id=f"mwgenerated_{token}_cell_{row_index}_{column_index}",
                row_id=row_id,
                column_id=column.column_id,
                text=str(values[column_index]) if column_index < len(values) else "",
                style_role=role,
            )
            for column_index, column in enumerate(columns)
        ],
    )


def _identifier_token(value: str) -> str:
    token = "".join(character for character in value.lower() if character.isalnum())
    if not token:
        raise ValueError("template instance id is empty")
    return token
