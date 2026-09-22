from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from packages.contracts.workbench_contracts import (
    MedicalWritingGreenfieldSectionSeed,
    MedicalWritingProtocolModuleResolution,
    MedicalWritingProtocolTemplateDefinition,
    MedicalWritingProtocolTemplateNode,
)

from .medical_writing_design_projection import normalize_study_design


TEMPLATE_ID = "cms_protocol_zh_cn"
TEMPLATE_VERSION = "cms_protocol_zh_cn_company_authority_2026_07_19_v2"
M11_TEMPLATE_ID = "ich_m11_zh_cn"
M11_TEMPLATE_VERSION = "ich_m11_zh_cn_step4_cde_consultation_2026_06_12_v1"
DRAFT_TEMPLATE_VERSION = "ich_m11_zh_cn_draft_2025_01_14_v1"

CMS_D017_PNH_SYNOPSIS = "cms_d017_pnh_synopsis_v0_2"
CMS_D005_OBESITY_SYNOPSIS = "cms_d005_obesity_synopsis_v0_3"
MY004_RA_SYNOPSIS = "my004_ra_synopsis_v0_3"
MY004_DERMATOLOGY_SYNOPSIS = "my004_dermatology_synopsis_v0_4"
CMS_D017_PHASE1_PROTOCOL = "cms_d017_phase1_protocol_v1_1"
CMS_D001_PHASE2_PROTOCOL = "cms_d001_ad_phase2_protocol_v1_0"
MGK10_PHASE3_PROTOCOL = "mgk10_ad_phase3_protocol_v1_0"

PROTOCOL_STRUCTURE_PANEL_ID = (
    "ctgov_protocol_structure_panel_ad_ra_pso_phase2_phase3_20260719_v1"
)
COMPANY_STRUCTURE_AUTHORITY_ID = (
    "cms_company_protocol_structure_authority_20260719_v1"
)
STRUCTURAL_EVIDENCE_NOTE = (
    "外部30份公开Protocol仅提供跨申办方结构观察，不决定章节必要性；"
    "公司权威模板及已确认的项目设计事实决定最终渲染。"
)

REPEATABLE_OBJECTIVE_NODE_IDS = frozenset(
    {
        "ich_m11_3_1_1",
        "ich_m11_3_2_1",
        "ich_m11_3_3_1",
        "ich_m11_10_4_1",
        "ich_m11_10_5_1",
    }
)


def materialize_repeatable_objective_heading(
    title: str,
    *,
    template_node_id: str,
    instance_index: int = 1,
    instance_count: int = 1,
) -> str:
    """Resolve the M11 ``<#>`` title marker for one project instance."""

    if template_node_id not in REPEATABLE_OBJECTIVE_NODE_IDS or "<#>" not in title:
        return title
    if instance_index < 1 or instance_count < 1 or instance_index > instance_count:
        raise ValueError("repeatable objective instance coordinates are invalid")
    suffix = "" if instance_count == 1 else f" {instance_index}"
    return re.sub(r"\s*<#>", suffix, title, count=1).strip()

_DRAFT_CHAPTERS = """
1|方案概要
1.1|方案摘要
1.1.1|主要和次要目的及估计目标
1.1.2|总体设计
1.2|试验方案
1.3|活动时间表
2|引言
2.1|试验目的
2.2|获益和风险评估
2.2.1|风险总结和缓解策略
2.2.2|获益总结
2.2.3|总体获益-风险评估
3|试验目的和相关估计目标
3.1|主要目的和相关估计目标
3.1.1|主要目的 <#>
3.2|次要目的和相关估计目标
3.2.1|次要目的 <#>
3.3|探索性目的
3.3.1|探索性目的 <#>
4|试验设计
4.1|试验设计描述
4.1.1|利益相关方对设计的影响和建议
4.2|试验设计依据
4.2.1|估计目标的依据
4.2.2|干预模式的依据
4.2.3|对照类型的依据
4.2.4|试验持续时间的依据
4.2.5|适应性或新颖试验设计的依据
4.2.6|期中分析的依据
4.2.7|其他试验设计方面的依据
4.3|试验停止规则
4.4|试验开始和结束
4.5|试验结束后获得试验干预
5|试验人群
5.1|试验人群描述和依据
5.2|入选标准
5.3|排除标准
5.4|避孕
5.4.1|与生育能力相关的定义
5.4.2|避孕要求
5.5|生活方式限制
5.5.1|用餐和饮食限制
5.5.2|咖啡因、酒精、烟草和其他限制
5.5.3|身体活动限制
5.5.4|其他活动限制
5.6|筛选失败和重新筛选
6|试验干预和合并治疗
6.1|研究性干预描述
6.2|研究性干预剂量和方案的依据
6.3|研究性干预管理
6.4|研究性干预剂量调整
6.5|研究性干预药物过量的管理
6.6|研究性干预的制备、储存、处理和管理
6.6.1|研究性干预准备
6.6.2|研究性干预的储存和处理
6.6.3|研究性干预管理
6.7|研究性干预分配、随机化和设盲
6.7.1|受试者分配至研究性干预组
6.7.2|随机分组
6.7.3|保持盲态的措施
6.7.4|研究中心紧急揭盲
6.8|研究性干预依从性
6.9|非研究性干预描述
6.9.1|基础试验干预
6.9.2|补救治疗
6.9.3|其他非研究性干预
6.10|合并治疗
6.10.1|禁止的合并治疗
6.10.2|允许的合并治疗
7|受试者试验干预终止以及终止或退出试验
7.1|个体受试者试验干预终止
7.1.1|试验干预永久终止
7.1.2|试验干预暂时终止
7.1.3|再激发
7.2|受试者终止或退出试验
7.3|失访管理
8|试验评估和程序
8.1|试验评估和程序考虑因素
8.2|筛选/基线评估和程序
8.3|有效性评估和程序
8.4|安全性评估和程序
8.4.1|体格检查
8.4.2|生命体征
8.4.3|心电图
8.4.4|临床实验室评估
8.4.5|妊娠试验
8.4.6|自杀意念和行为风险监测
8.5|药代动力学
8.6|生物标志物
8.6.1|遗传学和药物基因组学
8.6.2|药效动力学生物标志物
8.6.3|其他生物标志物
8.7|免疫原性评估
8.8|医疗资源利用与卫生经济学
9|不良事件、严重不良事件、产品投诉、妊娠和产后信息以及特殊安全性情况
9.1|定义
9.1.1|不良事件定义
9.1.2|严重不良事件定义
9.1.3|产品投诉的定义
9.1.3.1|医疗器械产品投诉的定义
9.2|收集和报告的时间和程序
9.2.1|时间
9.2.2|收集程序
9.2.3|报告
9.2.3.1|监管报告要求
9.2.4|特别关注的不良事件
9.2.5|不属于 AE 或 SAE 的疾病相关事件或结局
9.3|妊娠和产后信息
9.3.1|试验期间怀孕的受试者
9.3.2|试验期间伴侣怀孕的受试者
9.4|特殊安全性情况
10|统计考虑因素
10.1|一般考虑因素
10.2|分析集
10.3|人口统计学和其他基线变量分析
10.4|与主要目的相关的分析
10.4.1|主要目的 <#>
10.4.1.1|统计分析方法
10.4.1.2|与主要估计目标相关的数据处理
10.4.1.3|与主要估计目标相关的缺失数据处理
10.4.1.4|敏感性分析
10.4.1.5|补充分析
10.5|与次要目的相关的分析
10.5.1|次要目的 <#>
10.5.1.1|统计分析方法
10.5.1.2|与次要估计目标相关的数据处理
10.5.1.3|与次要估计目标相关的缺失数据处理
10.5.1.4|敏感性分析
10.5.1.5|补充分析
10.6|与探索性目的相关的分析
10.7|安全性分析
10.8|其他分析
10.9|期中分析
10.10|多重性调整
10.11|样本量确定
11|试验监督和其他一般考虑因素
11.1|监管和伦理考量
11.2|试验监督
11.2.1|研究者职责
11.2.2|申办方职责
11.3|知情同意程序
11.3.1|重新筛选知情同意书
11.3.2|剩余样本用于探索性研究知情同意书
11.4|委员会
11.5|保险和赔偿
11.6|基于风险的质量管理
11.7|数据管理
11.8|数据保护
11.9|源数据
11.10|方案偏离
11.11|研究中心提前关闭
11.12|数据发布
12|附录：支持性细节
12.1|临床实验室检查
12.2|国家/地区特定差异
12.3|既往方案修正案
13|附录：术语和缩略语表
14|附录：参考文献
""".strip()

_STEP4_CHAPTERS = """
1|方案概要
1.1|方案摘要
1.1.1|主要和次要目的及估计目标
1.1.2|总体设计
1.2|试验示意图
1.3|活动时间表
2|引言
2.1|试验目的
2.2|获益和风险评估
2.2.1|风险总结和缓解策略
2.2.2|获益总结
2.2.3|总体获益-风险评估
3|试验目的和相关估计目标
3.1|主要目的和相关估计目标
3.1.1|主要目的 <#>
3.2|次要目的和相关估计目标
3.2.1|次要目的 <#>
3.3|探索性目的
3.3.1|探索性目的 <#>
4|试验设计
4.1|试验设计描述
4.1.1|利益相关方对设计的影响和建议
4.2|试验设计依据
4.2.1|估计目标的依据
4.2.2|干预模式的依据
4.2.3|对照类型的依据
4.2.4|试验持续时间的依据
4.2.5|适应性或新颖试验设计的依据
4.2.6|期中分析的依据
4.2.7|其他试验设计方面的依据
4.3|试验停止规则
4.4|试验开始和结束
4.5|试验结束后获得试验干预
5|试验人群
5.1|试验人群描述和依据
5.2|入选标准
5.3|排除标准
5.4|避孕
5.4.1|与生育能力相关的定义
5.4.2|避孕要求
5.5|生活方式限制
5.5.1|用餐和饮食限制
5.5.2|咖啡因、酒精、烟草和其他限制
5.5.3|身体活动限制
5.5.4|其他活动限制
5.6|筛选失败和重新筛选
6|试验干预和合并治疗
6.1|临床试验干预描述
6.2|临床试验干预剂量和方案的依据
6.3|临床试验干预管理
6.4|临床试验干预剂量调整
6.5|临床试验干预药物过量的管理
6.6|临床试验干预的制备、储存、处理和管理
6.6.1|临床试验干预准备
6.6.2|临床试验干预的储存和处理
6.6.3|临床试验干预管理
6.7|临床试验干预分配、随机化和设盲
6.7.1|试验参与者分配至临床试验干预组
6.7.2|随机分组
6.7.3|保持盲态的措施
6.7.4|研究中心紧急揭盲
6.8|临床试验干预依从性
6.9|非临床试验干预描述
6.9.1|基础试验干预
6.9.2|补救治疗
6.9.3|其他非临床试验干预
6.10|合并治疗
6.10.1|禁止的合并治疗
6.10.2|允许的合并治疗
7|试验参与者试验干预终止以及终止或退出试验
7.1|个体试验参与者试验干预终止
7.1.1|试验干预永久终止
7.1.2|试验干预暂时终止
7.1.3|再激发
7.2|试验参与者终止或退出试验
7.3|失访管理
8|试验评估和程序
8.1|试验评估和程序考虑因素
8.2|筛选/基线评估和程序
8.3|有效性评估和程序
8.4|安全性评估和程序
8.4.1|体格检查
8.4.2|生命体征
8.4.3|心电图
8.4.4|临床实验室评估
8.4.5|妊娠试验
8.4.6|自杀意念和行为风险监测
8.5|药代动力学
8.6|生物标志物
8.6.1|遗传学、基因组学、药物遗传学和药物基因组学
8.6.2|药效动力学生物标志物
8.6.3|其他生物标志物
8.7|免疫原性评估
8.8|医疗资源利用与卫生经济学
9|不良事件、严重不良事件、产品投诉、妊娠和产后信息以及特殊安全性情况
9.1|定义
9.1.1|不良事件定义
9.1.2|严重不良事件定义
9.1.3|产品投诉的定义
9.1.3.1|医疗器械产品投诉的定义
9.2|收集和报告的时间和程序
9.2.1|时间
9.2.2|收集程序
9.2.3|报告
9.2.3.1|监管报告要求
9.2.4|特别关注的不良事件
9.2.5|不属于 AE 或 SAE 的疾病相关事件或结局
9.3|妊娠和产后信息
9.3.1|试验期间怀孕的试验参与者
9.3.2|试验期间伴侣怀孕的试验参与者
9.4|特殊安全性情况
10|统计考虑因素
10.1|一般考虑因素
10.2|分析集
10.3|人口统计学和其他基线变量分析
10.4|与主要目的相关的分析
10.4.1|主要目的 <#>
10.4.1.1|统计分析方法
10.4.1.2|与主要估计目标相关的数据处理
10.4.1.3|与主要估计目标相关的缺失数据处理
10.4.1.4|敏感性分析
10.4.1.5|补充分析
10.5|与次要目的相关的分析
10.5.1|次要目的 <#>
10.5.1.1|统计分析方法
10.5.1.2|与次要估计目标相关的数据处理
10.5.1.3|与次要估计目标相关的缺失数据处理
10.5.1.4|敏感性分析
10.5.1.5|补充分析
10.6|与探索性目的相关的分析
10.7|安全性分析
10.8|其他分析
10.9|期中分析
10.10|多重性调整
10.11|样本量确定
11|试验监督和其他一般考虑因素
11.1|监管和伦理考量
11.2|试验监督
11.2.1|研究者职责
11.2.2|申办者职责
11.3|知情同意程序
11.3.1|重新筛选的知情同意书
11.3.2|剩余样本用于探索性研究知情同意书
11.4|委员会
11.5|保险和赔偿
11.6|基于风险的质量管理
11.7|数据管理
11.8|数据保护
11.9|源记录
11.10|方案偏离
11.11|研究中心提前关闭
11.12|数据发布
12|附录：支持性细节
12.1|临床实验室检查
12.2|国家/地区特定差异
12.3|既往方案修正案
12.X|附加附录
13|附录：术语和缩略语表
14|附录：参考文献
""".strip()

# Company-facing title tree distilled from the supplied I/II/III phase protocols.
# Each row is: catalog number | stable semantic id | display title |
# comma-separated applicability rules | comma-separated M11 coverage anchors.
# Catalog numbers only preserve hierarchy/order; selected project seeds are
# renumbered continuously after conditional modules are removed.
_COMPANY_CHAPTERS = """
1|synopsis|方案概要||1
1.1|synopsis.summary|方案摘要||1.1
1.2|synopsis.schema|研究示意图||1.2
1.3|synopsis.schedule|研究流程表||1.3
2|background|研究背景和立项依据||2
2.1|background.disease|疾病背景及治疗现状||2
2.2|background.mechanism|作用机制及同类药物研究进展||2
2.3|background.product|研究药物简介||2
2.3.1|background.product.nonclinical|非临床研究结果||2
2.3.2|background.product.clinical|既往临床研究结果||2
2.4|background.rationale|本研究的理论基础||2.1
2.5|background.benefit_risk|获益/风险评估||2.2
3|objectives_endpoints|研究目的和终点||3
3.1|objectives_endpoints.primary|主要目的和主要终点||3.1
3.2|objectives_endpoints.secondary|次要目的和次要终点||3.2
3.3|objectives_endpoints.exploratory|探索性目的和探索性终点||3.3
4|study_design|研究设计||4
4.1|study_design.overall|总体设计||4.1
4.2|study_design.phase1_parts|I期研究组成|phase:1|4.1
4.2.1|study_design.phase1_sad|单次给药剂量递增研究|phase:1,phase1:sad|4.1
4.2.2|study_design.phase1_mad|多次给药剂量递增研究|phase:1,phase1:mad|4.1
4.2.3|study_design.phase1_food_effect|食物影响研究|phase:1,phase1:food_effect|4.1
4.2.4|study_design.phase1_special_population|特殊人群研究|phase:1,phase1:special_population|4.1
4.3|study_design.rationale|设计依据||4.2
4.3.1|study_design.starting_dose|起始剂量设置依据|phase:1|4.2.2
4.3.2|study_design.escalation|剂量递增与停止规则|phase:1|4.3
4.3.3|study_design.dose_selection|剂量选择依据|phase:2|4.2
4.3.4|study_design.confirmatory|确证性设计与假设依据|phase:3|4.2
4.3.5|study_design.pk_pd_sampling|PK/PD采集点设计依据|feature:pk_or_pd|4.2
4.4|study_design.randomization|随机化|design:randomized|6.7.2
4.5|study_design.blinding|盲法与揭盲|design:blinded|6.7.3,6.7.4
4.6|study_design.safety_committee|安全性审评/数据监查委员会|feature:safety_committee|11.4
4.7|study_design.study_end|研究结束与研究持续时间||4.4
4.8|study_design.pause_stop|研究暂停和终止标准||4.3
5|population|研究人群||5
5.1|population.size|计划入组人数||5.1
5.2|population.selection|研究人群选择及依据||5.1
5.3|population.inclusion|入选标准||5.2
5.4|population.exclusion|排除标准||5.3
5.5|population.screen_failure|筛选失败与重新筛选||5.6
5.6|population.replacement|参与者替换|phase:1|5
6|intervention|研究治疗/干预||6
6.1|intervention.product|试验用药品||6.1
6.1.1|intervention.product_description|研究药物信息||6.1
6.1.2|intervention.preparation_storage|制备、包装、标签、储存与管理||6.6
6.1.3|intervention.accountability|发放、回收与清点||6.6
6.2|intervention.regimen|研究治疗给药||6.3
6.3|intervention.dose_modification|剂量调整、暂停、恢复与永久停药||6.4
6.4|intervention.overdose_error|药物过量与给药错误管理||6.5
6.5|intervention.compliance|研究治疗依从性||6.8
6.6|intervention.concomitant|合并用药/治疗||6.10
6.6.1|intervention.concomitant_allowed|允许的合并用药/治疗||6.10.2
6.6.2|intervention.concomitant_prohibited|禁止的合并用药/治疗||6.10.1
6.6.3|intervention.background|必须使用的背景治疗|feature:background_therapy|6.9.1
6.6.4|intervention.rescue|补救治疗|feature:rescue_therapy|6.9.2
7|procedures_assessments|研究程序和评估||8
7.1|procedures_assessments.schedule|研究程序||8.1
7.1.1|procedures_assessments.screening|筛选期与基线||8.2
7.1.2|procedures_assessments.treatment_followup|治疗期及随访||8.1
7.1.3|procedures_assessments.unscheduled|计划外访视||8.1
7.1.4|procedures_assessments.withdrawal|研究治疗终止、退出研究及失访处理||7
7.2|procedures_assessments.efficacy|有效性评估||8.3
7.3|procedures_assessments.safety|安全性评估||8.4
7.3.1|procedures_assessments.vital_physical|生命体征和体格检查||8.4.1,8.4.2
7.3.2|procedures_assessments.ecg|心电图检查||8.4.3
7.3.3|procedures_assessments.laboratory|实验室检查||8.4.4,12.1
7.3.4|procedures_assessments.pregnancy|妊娠检查和避孕问询||8.4.5
7.4|procedures_assessments.pk|药代动力学评估|feature:pk|8.5
7.5|procedures_assessments.pd|药效动力学评估|feature:pd|8.6.2
7.6|procedures_assessments.immunogenicity|免疫原性评估|feature:immunogenicity|8.7
7.7|procedures_assessments.biomarker|生物标志物评估|feature:biomarker|8.6
7.8|procedures_assessments.specimen|生物样本采集、处置与保存|feature:biological_specimen|8.6
8|safety|安全性评价||9
8.1|safety.general|总则||9
8.2|safety.definitions|定义||9.1
8.2.1|safety.ae|不良事件||9.1.1
8.2.2|safety.sae|严重不良事件||9.1.2
8.2.3|safety.susar|可疑且非预期严重不良反应||9.1
8.3|safety.product_risks|研究药物相关风险||2.2.1
8.4|safety.collection|不良事件的采集与记录||9.2
8.5|safety.assessment|不良事件的评估||9.2
8.6|safety.reporting|不良事件的报告||9.2.3
8.7|safety.followup|不良事件的随访||9.2
8.8|safety.aesi|特别关注的不良事件|feature:aesi|9.2.4
8.9|safety.pregnancy|妊娠事件的报告与随访||9.3
9|statistics|统计分析||10
9.1|statistics.sample_size|样本量||10.11
9.2|statistics.analysis_sets|统计分析数据集||10.2
9.3|statistics.general|统计分析一般原则||10.1
9.4|statistics.efficacy|有效性数据分析||10.4,10.5,10.6
9.5|statistics.safety|安全性数据分析||10.7
9.6|statistics.pk|PK数据分析|feature:pk|10.8
9.7|statistics.pd|PD数据分析|feature:pd|10.8
9.8|statistics.er|暴露-效应分析|feature:er|10.8
9.9|statistics.interim|期中分析|feature:interim_analysis|10.9
9.10|statistics.multiplicity|多重性控制|feature:multiplicity|10.10
9.11|statistics.subgroup|亚组及其他分析|feature:subgroup|10.8
10|data_management|数据采集与管理||11.7
10.1|data_management.crf|病例报告表||11.7
10.2|data_management.source|数据源的定义||11.9
10.3|data_management.quality|数据质量保证||11.6,11.7
10.4|data_management.retention|资料保存与数据保护||11.8
10.5|data_management.publication|数据发布和研究发表策略||11.12
11|ethics|伦理考虑||11.1
11.1|ethics.compliance|遵守法律法规||11.1
11.2|ethics.consent|知情同意||11.3
11.3|ethics.committee|伦理委员会||11.1
11.4|ethics.privacy|保密与隐私||11.8
11.5|ethics.insurance|保险与赔偿||11.5
12|study_management|研究文件、监查和管理||11.2
12.1|study_management.compliance|研究方案的依从||11.2
12.2|study_management.monitoring|监查||11.2
12.3|study_management.audit_inspection|稽查和核查||11.2
12.4|study_management.deviation|方案偏离||11.10
12.5|study_management.roles|关键角色和研究管理||11.2
12.6|study_management.closeout|研究和研究中心的关闭||11.11
12.7|study_management.quality|质量控制与保证||11.6
13|references|参考文献||14
14|appendices|附录||12,13
14.1|appendices.contraception|避孕的规定与方法|feature:contraception|5.4
14.2|appendices.instruments|研究量表和评价工具|feature:assessment_instrument|12.X
14.3|appendices.lab_panels|实验室检查项目|feature:lab_panel|12.1
14.4|appendices.safety_reporting|安全信息报告途径||12.X
14.5|appendices.project_specific|项目特异附录||12.X
""".strip()

_CONDITIONAL_PREFIXES = (
    "2.2.1", "2.2.2", "2.2.3", "4.1.1", "4.2.1", "4.2.2", "4.2.3",
    "4.2.4", "4.2.5", "4.2.6", "4.2.7", "4.5", "5.4", "5.5", "6.7.2",
    "6.7.3", "6.7.4", "6.9", "6.10.2", "7.1.3", "8.4.1", "8.4.2",
    "8.4.3", "8.4.4", "8.4.5", "8.4.6", "8.5", "8.6", "8.7", "8.8",
    "9.1.3.1", "9.2.5", "9.3.1", "9.3.2", "10.4.1.4", "10.4.1.5",
    "10.5.1", "10.9", "10.10", "11.2.1", "11.2.2", "11.3.1", "11.3.2", "11.4",
    "12.X",
)


def _node_id(number: str) -> str:
    return f"ich_m11_{number.replace('.', '_')}"


def _company_node_id(semantic_node_id: str) -> str:
    return "cms_" + re.sub(r"[^a-z0-9]+", "_", semantic_node_id.lower()).strip("_")


def _parent_number(number: str) -> str:
    return number.rsplit(".", 1)[0] if "." in number else ""


def _node_kind(number: str) -> str:
    return {
        "1.1": "protocol_synopsis",
        "1.2": "study_schema",
        "1.3": "schedule_of_activities",
        "12": "appendix",
        "13": "glossary",
        "14": "references",
    }.get(number, "section")


def _interactions(number: str) -> list[str]:
    special = {
        "1.1": ["synopsis_editor", "structured_table"],
        "1.2": ["study_schema_editor"],
        "1.3": ["schedule_of_activities_editor"],
        "5.2": ["eligibility_rule_builder", "candidate_text", "rich_text"],
        "5.3": ["eligibility_rule_builder", "candidate_text", "rich_text"],
        "6.4": ["dose_modification_rule_builder", "structured_table", "rich_text"],
        "6.9": ["non_investigational_intervention_builder", "rich_text"],
        "6.10": ["concomitant_therapy_rule_builder", "rich_text"],
        "8.3": ["assessment_instrument_builder", "candidate_text", "rich_text"],
        "9.2.4": ["aesi_rule_builder", "structured_table", "rich_text"],
        "10.2": ["analysis_set_builder", "structured_table", "rich_text"],
        "10.11": ["sample_size_builder", "structured_table", "rich_text"],
        "12.1": ["laboratory_panel_editor", "structured_table"],
        "12.2": ["regional_difference_editor", "structured_table"],
        "12.3": ["amendment_history_editor", "structured_table"],
        "13": ["glossary_editor", "structured_table"],
        "14": ["reference_manager"],
    }
    if number in special:
        return special[number]
    if number.startswith("3."):
        return ["objective_estimand_builder", "candidate_text", "rich_text"]
    return ["module_builder", "candidate_text", "rich_text"]


def _company_interactions(semantic_node_id: str) -> list[str]:
    special = {
        "synopsis.summary": ["synopsis_editor", "structured_table"],
        "synopsis.schema": ["study_schema_editor"],
        "synopsis.schedule": ["schedule_of_activities_editor"],
        "population.inclusion": ["eligibility_rule_builder", "candidate_text", "rich_text"],
        "population.exclusion": ["eligibility_rule_builder", "candidate_text", "rich_text"],
        "intervention.dose_modification": [
            "dose_modification_rule_builder",
            "structured_table",
            "rich_text",
        ],
        "intervention.concomitant": [
            "concomitant_therapy_rule_builder",
            "rich_text",
        ],
        "procedures_assessments.efficacy": [
            "assessment_instrument_builder",
            "candidate_text",
            "rich_text",
        ],
        "safety.aesi": ["aesi_rule_builder", "structured_table", "rich_text"],
        "statistics.analysis_sets": [
            "analysis_set_builder",
            "structured_table",
            "rich_text",
        ],
        "statistics.sample_size": [
            "sample_size_builder",
            "structured_table",
            "rich_text",
        ],
        "references": ["reference_manager"],
    }
    if semantic_node_id in special:
        return special[semantic_node_id]
    if semantic_node_id.startswith("objectives_endpoints."):
        return ["objective_endpoint_builder", "candidate_text", "rich_text"]
    if semantic_node_id.startswith("appendices."):
        return ["module_builder", "structured_table", "rich_text"]
    return ["module_builder", "candidate_text", "rich_text"]


def _structural_function_ids(semantic_node_id: str) -> list[str]:
    if semantic_node_id in {
        "synopsis.schedule",
        "procedures_assessments",
        "procedures_assessments.schedule",
        "procedures_assessments.screening",
        "procedures_assessments.treatment_followup",
        "procedures_assessments.unscheduled",
    }:
        return ["F09_schedule_of_activities"]
    if semantic_node_id == "procedures_assessments.withdrawal":
        return ["F08_disposition_withdrawal"]
    if semantic_node_id in {
        "procedures_assessments.efficacy",
        "appendices.instruments",
    }:
        return ["F10_efficacy_assessment"]
    if semantic_node_id.startswith("procedures_assessments."):
        if semantic_node_id in {
            "procedures_assessments.pk",
            "procedures_assessments.pd",
            "procedures_assessments.immunogenicity",
            "procedures_assessments.biomarker",
            "procedures_assessments.specimen",
        }:
            return ["F12_pk_pd_immunogenicity"]
        return ["F11_safety_assessment_oversight"]
    if semantic_node_id in {
        "appendices.contraception",
    }:
        return ["F06_population_eligibility"]
    if semantic_node_id in {
        "appendices.lab_panels",
        "appendices.safety_reporting",
    }:
        return ["F11_safety_assessment_oversight"]
    prefix_map = (
        ("document_control.", "F01_document_control"),
        ("synopsis", "F02_synopsis"),
        ("background", "F03_rationale_benefit_risk"),
        ("objectives_endpoints", "F04_objectives_endpoints_estimands"),
        ("study_design", "F05_study_design"),
        ("population", "F06_population_eligibility"),
        ("intervention", "F07_intervention_treatment"),
        ("safety", "F11_safety_assessment_oversight"),
        ("statistics", "F13_statistical_methodology"),
        ("data_management", "F14_governance_compliance"),
        ("ethics", "F14_governance_compliance"),
        ("study_management", "F14_governance_compliance"),
        ("references", "F14_governance_compliance"),
        ("appendices", "F14_governance_compliance"),
    )
    for prefix, function_id in prefix_map:
        if semantic_node_id.startswith(prefix):
            return [function_id]
    return ["F14_governance_compliance"]


def _structural_evidence_class(applicability_rules: list[str]) -> str:
    if not applicability_rules:
        return "company_core"
    if all(rule.startswith("phase:") for rule in applicability_rules):
        return "phase_core"
    if any(
        rule
        in {
            "feature:immunogenicity",
            "feature:biomarker",
            "feature:assessment_instrument",
            "feature:lab_panel",
        }
        for rule in applicability_rules
    ):
        return "modality_or_indication_optional"
    return "design_optional"


def render_assessment_instrument_methods(definition: Any) -> str:
    """Render confirmed project-use metadata without reproducing instrument items."""
    rows: list[str] = []
    for item in getattr(definition.picos, "assessment_instruments", []):
        if item.confirmation_status != "confirmed":
            continue
        label = item.acronym.strip()
        if item.canonical_name_zh.strip():
            label = (
                f"{label}（{item.canonical_name_zh.strip()}）"
                if label
                else item.canonical_name_zh.strip()
            )
        details: list[str] = []
        if item.respondent.strip():
            details.append(f"实施者为{item.respondent.strip()}")
        if item.administration_mode.strip():
            details.append(f"实施方式为{item.administration_mode.strip()}")
        if item.recall_period.strip():
            details.append(f"回忆期为{item.recall_period.strip()}")
        if item.visit_labels:
            details.append("评价时点包括" + "、".join(item.visit_labels))
        if item.study_purpose.strip():
            details.append(item.study_purpose.strip())
        scoring = "，".join(
            value.strip()
            for value in (item.scoring_range, item.scoring_direction)
            if value.strip()
        )
        if scoring:
            details.append(scoring)
        if item.protocol_modified:
            details.append("本研究采用的项目特定实施版本须与经确认的量表版本保持一致")
        if label and details:
            rows.append(f"{label}：{'；'.join(details)}。")
    return "\n".join(rows)


_M11_APPLICABILITY_RULES: dict[str, list[str]] = {
    "4.2.6": ["feature:interim_analysis"],
    "10.9": ["feature:interim_analysis"],
}


def _nodes(chapters: str) -> list[MedicalWritingProtocolTemplateNode]:
    nodes = [
        MedicalWritingProtocolTemplateNode(
            node_id="ich_m11_front_matter",
            semantic_node_id="document_control.front_matter",
            section_number="",
            parent_node_id="",
            title_zh="方案首页与版本信息",
            level=0,
            node_kind="front_matter",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["front_matter_editor"],
            include_in_toc=False,
            authority_source_ids=["ich_m11_template"],
        )
    ]
    for row in chapters.splitlines():
        number, title = row.split("|", 1)
        parent = _parent_number(number)
        applicability_rules = _M11_APPLICABILITY_RULES.get(number, [])
        nodes.append(
            MedicalWritingProtocolTemplateNode(
                node_id=_node_id(number),
                semantic_node_id=f"m11.{number}",
                section_number=number,
                parent_node_id=_node_id(parent) if parent else "",
                title_zh=title,
                level=number.count(".") + 1,
                node_kind=_node_kind(number),
                applicability_mode=(
                    "conditional_by_design"
                    if any(number == item or number.startswith(f"{item}.") for item in _CONDITIONAL_PREFIXES)
                    else "required"
                ),
                repeatable="<#>" in title or number == "12.X",
                title_locked=number != "12.X",
                interaction_types=_interactions(number),
                include_in_toc=True,
                applicability_rules=applicability_rules,
                authority_source_ids=["ich_m11_template"],
                m11_coverage_anchors=[number],
            )
        )
    return nodes


def _company_nodes() -> list[MedicalWritingProtocolTemplateNode]:
    core_sources = [
        CMS_D017_PHASE1_PROTOCOL,
        CMS_D001_PHASE2_PROTOCOL,
        MGK10_PHASE3_PROTOCOL,
    ]
    synopsis_sources = [
        CMS_D017_PNH_SYNOPSIS,
        CMS_D005_OBESITY_SYNOPSIS,
        MY004_RA_SYNOPSIS,
        MY004_DERMATOLOGY_SYNOPSIS,
    ]
    nodes = [
        MedicalWritingProtocolTemplateNode(
            node_id="cms_front_matter",
            semantic_node_id="document_control.front_matter",
            section_number="",
            parent_node_id="",
            title_zh="方案首页与版本信息",
            level=0,
            node_kind="front_matter",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["front_matter_editor"],
            include_in_toc=False,
            authority_source_ids=[*synopsis_sources, *core_sources],
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
        MedicalWritingProtocolTemplateNode(
            node_id="cms_confidentiality",
            semantic_node_id="document_control.confidentiality",
            section_number="",
            parent_node_id="",
            title_zh="保密声明",
            level=0,
            node_kind="document_control",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["document_control_editor", "rich_text"],
            include_in_toc=False,
            authority_source_ids=core_sources,
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
        MedicalWritingProtocolTemplateNode(
            node_id="cms_signatures",
            semantic_node_id="document_control.signatures",
            section_number="",
            parent_node_id="",
            title_zh="签字页",
            level=0,
            node_kind="document_control",
            applicability_mode="required",
            repeatable=True,
            title_locked=True,
            interaction_types=["document_control_editor", "structured_table"],
            include_in_toc=False,
            authority_source_ids=core_sources,
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
        MedicalWritingProtocolTemplateNode(
            node_id="cms_version_history",
            semantic_node_id="document_control.version_history",
            section_number="",
            parent_node_id="",
            title_zh="研究方案版本更新记录",
            level=0,
            node_kind="document_control",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["amendment_history_editor", "structured_table"],
            include_in_toc=False,
            authority_source_ids=core_sources,
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
        MedicalWritingProtocolTemplateNode(
            node_id="cms_indexes",
            semantic_node_id="document_control.indexes",
            section_number="",
            parent_node_id="",
            title_zh="目录、表目录和图目录",
            level=0,
            node_kind="document_control",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["document_index_editor"],
            include_in_toc=False,
            authority_source_ids=core_sources,
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
        MedicalWritingProtocolTemplateNode(
            node_id="cms_glossary",
            semantic_node_id="document_control.glossary",
            section_number="",
            parent_node_id="",
            title_zh="缩略语与术语定义",
            level=0,
            node_kind="glossary",
            applicability_mode="required",
            repeatable=False,
            title_locked=True,
            interaction_types=["glossary_editor", "structured_table"],
            include_in_toc=True,
            authority_source_ids=core_sources,
            m11_coverage_anchors=["13"],
            structural_function_ids=["F01_document_control"],
            structural_evidence_class="company_core",
            structural_evidence_refs=[
                COMPANY_STRUCTURE_AUTHORITY_ID,
                PROTOCOL_STRUCTURE_PANEL_ID,
            ],
            structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
        ),
    ]
    by_number: dict[str, str] = {}
    for raw_row in _COMPANY_CHAPTERS.splitlines():
        number, semantic_node_id, title, raw_rules, raw_anchors = raw_row.split("|", 4)
        node_id = _company_node_id(semantic_node_id)
        parent_number = _parent_number(number)
        by_number[number] = node_id
        authority_sources = (
            list(synopsis_sources)
            if semantic_node_id.startswith("synopsis")
            else list(core_sources)
        )
        applicability_rules = [
            item.strip() for item in raw_rules.split(",") if item.strip()
        ]
        nodes.append(
            MedicalWritingProtocolTemplateNode(
                node_id=node_id,
                semantic_node_id=semantic_node_id,
                section_number=number,
                parent_node_id=by_number.get(parent_number, ""),
                title_zh=title,
                level=number.count(".") + 1,
                node_kind={
                    "synopsis.summary": "protocol_synopsis",
                    "synopsis.schema": "study_schema",
                    "synopsis.schedule": "schedule_of_activities",
                    "references": "references",
                    "appendices": "appendix",
                }.get(semantic_node_id, "section"),
                applicability_mode=(
                    "conditional_by_plugin" if raw_rules.strip() else "required"
                ),
                repeatable=semantic_node_id in {
                    "synopsis.schedule",
                    "appendices.project_specific",
                },
                title_locked=semantic_node_id != "appendices.project_specific",
                interaction_types=_company_interactions(semantic_node_id),
                include_in_toc=True,
                applicability_rules=applicability_rules,
                authority_source_ids=authority_sources,
                m11_coverage_anchors=[
                    item.strip() for item in raw_anchors.split(",") if item.strip()
                ],
                structural_function_ids=_structural_function_ids(semantic_node_id),
                structural_evidence_class=_structural_evidence_class(
                    applicability_rules
                ),
                structural_evidence_refs=[
                    COMPANY_STRUCTURE_AUTHORITY_ID,
                    PROTOCOL_STRUCTURE_PANEL_ID,
                ],
                structural_evidence_note=STRUCTURAL_EVIDENCE_NOTE,
            )
        )
    return nodes


def company_template_semantic_node_map() -> dict[str, str]:
    """Return the source-authored template-node to semantic-node identity map.

    The full-draft bridge uses this stable identity at generation time.  It
    must never infer a semantic chapter from a translated heading or array
    position because both can change independently of the template contract.
    """
    return {node.node_id: node.semantic_node_id for node in _company_nodes()}


def _normalized_phase(value: str) -> str:
    token = str(value or "").upper().replace(" ", "")
    if any(item in token for item in ("Ⅲ", "III期", "PHASE3", "PHASEIII")):
        return "3"
    if any(item in token for item in ("Ⅱ", "II期", "PHASE2", "PHASEII")):
        return "2"
    if any(item in token for item in ("Ⅰ", "I期", "PHASE1", "PHASEI")):
        return "1"
    return ""


def _consumer_design_projection(definition: Any, design_projection: Any = None):
    if design_projection is not None:
        return design_projection
    framing = getattr(definition, "framing", None)
    if (
        framing is not None
        and hasattr(framing, "structured_design")
        and hasattr(definition, "state_sha256")
    ):
        return normalize_study_design(definition)
    return None


def _project_facets(definition: Any, design_projection: Any = None) -> set[str]:
    framing = definition.framing
    picos = definition.picos
    product = getattr(framing, "product_profile", None)
    design_projection = _consumer_design_projection(
        definition, design_projection
    )
    design_view = (
        design_projection.design_view if design_projection is not None else None
    )
    phase = _normalized_phase(
        getattr(design_view, "study_phase", "")
        if design_view is not None
        else getattr(framing, "study_phase", "")
    )
    facets = {f"phase:{phase}"} if phase else set()
    searchable = " ".join(
        [
            " ".join(getattr(framing, "intrinsic_objectives", []) or []),
            " ".join(getattr(product, "pk_pd_considerations", []) or []),
            getattr(picos, "primary_endpoint", ""),
            " ".join(getattr(picos, "key_secondary_endpoints", []) or []),
            " ".join(getattr(picos, "other_secondary_endpoints", []) or []),
            " ".join(getattr(picos, "exploratory_endpoints", []) or []),
            getattr(picos, "statistical_strategy", ""),
        ]
    ).lower()
    design_text = (
        getattr(framing, "design_pattern", "").lower()
        if design_view is None
        else ""
    )
    structured_design = getattr(framing, "structured_design", None)
    randomization_mode = (
        design_view.randomization_mode
        if design_view is not None
        else getattr(structured_design, "randomization_mode", "undecided")
    )
    blinding_mode = (
        design_view.blinding_mode
        if design_view is not None
        else getattr(structured_design, "blinding_mode", "undecided")
    )
    if randomization_mode == "randomized" or (
        design_view is None
        and ("随机" in design_text or "random" in design_text)
    ):
        facets.add("design:randomized")
    if blinding_mode in {"single_blind", "double_blind", "triple_blind"} or (
        design_view is None
        and any(item in design_text for item in ("双盲", "单盲", "盲法", "blind"))
    ):
        facets.add("design:blinded")
    if blinding_mode == "open_label" or (
        design_view is None
        and ("开放" in design_text or "open-label" in design_text)
    ):
        facets.add("design:open_label")
    # Phase I Part facets must come from NormalizedDesignProjection / typed
    # structured_design.phase1_parts only. Never invent SAD/MAD/etc. from
    # free-text framing.intrinsic_objectives or design_pattern prose.
    typed_phase1_parts = (
        list(design_view.phase1_parts)
        if design_view is not None
        else list(getattr(structured_design, "phase1_parts", None) or [])
    )
    selected_phase1_codes = {
        str(getattr(part, "part_code", "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        for part in typed_phase1_parts
        if str(getattr(part, "part_code", "") or "").strip()
    }
    structured_phase1_facets = {
        "phase1:sad": {"sad"},
        "phase1:mad": {"mad"},
        "phase1:food_effect": {"food_effect"},
        "phase1:special_population": {
            "hepatic_impairment",
            "renal_impairment",
            "mass_balance",
        },
    }
    for facet, codes in structured_phase1_facets.items():
        if selected_phase1_codes & codes:
            facets.add(facet)
    if any(item in searchable for item in ("pk", "药代", "暴露")) or phase == "1":
        facets.add("feature:pk")
    if any(item in searchable for item in ("pd", "药效", "生物标志")):
        facets.add("feature:pd")
    if {"feature:pk", "feature:pd"} & facets:
        facets.add("feature:pk_or_pd")
        facets.add("feature:biological_specimen")
    if any(item in searchable for item in ("暴露-效应", "暴露效应", "e-r", "exposure-response")):
        facets.add("feature:er")
    structured_interim = (
        design_view.interim_analysis
        if design_view is not None
        else getattr(structured_design, "interim_analysis", None)
    )
    interim_planned = getattr(structured_interim, "planned", None)
    if interim_planned is True or (
        interim_planned is not False
        and _mentions_planned_interim_analysis(
            getattr(framing, "design_pattern", ""),
            getattr(picos, "statistical_strategy", ""),
        )
    ):
        facets.add("feature:interim_analysis")
    if _mentions_planned_multiplicity_control(
        getattr(picos, "statistical_strategy", ""),
    ):
        facets.add("feature:multiplicity")
    if _mentions_planned_subgroup_analysis(
        getattr(picos, "statistical_strategy", ""),
    ):
        facets.add("feature:subgroup")
    if getattr(product, "immunogenicity_relevance", "unknown") in {
        "potential",
        "expected",
    } or getattr(product, "technology_type", "unknown") in {
        "monoclonal_antibody",
        "other_biologic",
        "rna_therapy",
        "cell_therapy",
        "gene_therapy",
        "vaccine",
    }:
        facets.add("feature:immunogenicity")
    if getattr(picos, "aesi_definitions", []):
        facets.add("feature:aesi")
    if getattr(picos, "assessment_instruments", []):
        facets.add("feature:assessment_instrument")
    if getattr(picos, "required_background_rules", []):
        facets.add("feature:background_therapy")
    rescue_text = " ".join(
        [
            *(getattr(picos, "allowed_concomitant_rules", []) or []),
            *(getattr(picos, "required_background_rules", []) or []),
        ]
    ).lower()
    if "补救" in rescue_text or "rescue" in rescue_text:
        facets.add("feature:rescue_therapy")
    if design_view is not None:
        if design_view.src_planned is True or design_view.dmc_planned is True:
            facets.add("feature:safety_committee")
        elif (
            phase == "1"
            and design_view.src_planned is not False
            and design_view.dmc_planned is not False
        ):
            # Phase I default unless SRC/DMC explicitly declined on the projection.
            facets.add("feature:safety_committee")
    elif getattr(product, "safety_considerations", []) or phase == "1":
        facets.add("feature:safety_committee")
    if getattr(picos, "inclusion_modules", []) or getattr(picos, "exclusion_modules", []):
        facets.update({"feature:contraception", "feature:lab_panel"})
    if any(item in searchable for item in ("生物标志", "biomarker")):
        facets.add("feature:biomarker")
    return facets


def _company_node_is_applicable(
    node: MedicalWritingProtocolTemplateNode,
    facets: set[str],
) -> bool:
    if node.applicability_mode == "required":
        return True
    return all(rule in facets for rule in node.applicability_rules)


_FACET_SOURCE_PATHS = {
    "phase:1": ("framing.study_phase",),
    "phase:2": ("framing.study_phase",),
    "phase:3": ("framing.study_phase",),
    "phase1:sad": ("framing.structured_design.phase1_parts",),
    "phase1:mad": ("framing.structured_design.phase1_parts",),
    "phase1:food_effect": ("framing.structured_design.phase1_parts",),
    "phase1:special_population": ("framing.structured_design.phase1_parts",),
    "design:randomized": ("framing.structured_design.randomization_mode",),
    "design:blinded": ("framing.structured_design.blinding_mode",),
    "feature:pk": ("framing.product_profile", "picos.statistical_strategy"),
    "feature:pd": ("framing.product_profile", "picos.statistical_strategy"),
    "feature:pk_or_pd": ("framing.product_profile", "picos.statistical_strategy"),
    "feature:biological_specimen": (
        "framing.product_profile",
        "picos.statistical_strategy",
    ),
    "feature:er": ("picos.statistical_strategy",),
    "feature:interim_analysis": (
        "framing.structured_design.interim_analysis",
    ),
    "feature:multiplicity": ("picos.statistical_strategy",),
    "feature:subgroup": ("picos.statistical_strategy",),
    "feature:immunogenicity": ("framing.product_profile",),
    "feature:aesi": ("picos.aesi_definitions",),
    "feature:assessment_instrument": ("picos.assessment_instruments",),
    "feature:background_therapy": ("picos.required_background_rules",),
    "feature:rescue_therapy": (
        "picos.allowed_concomitant_rules",
        "picos.required_background_rules",
    ),
    "feature:safety_committee": (
        "framing.structured_design.src_planned",
        "framing.structured_design.dmc_planned",
    ),
    "feature:contraception": (
        "picos.inclusion_modules",
        "picos.exclusion_modules",
    ),
    "feature:lab_panel": (
        "picos.inclusion_modules",
        "picos.exclusion_modules",
    ),
    "feature:biomarker": (
        "framing.product_profile",
        "picos.statistical_strategy",
    ),
}

_RETAIN_NA_SEMANTIC_NODES = {
    "safety.aesi",
    "study_design.safety_committee",
}


def _module_affected_artifacts(
    node: MedicalWritingProtocolTemplateNode,
) -> list[str]:
    semantic = node.semantic_node_id
    artifacts = ["body", "evidence", "ai_candidates"]
    if semantic.startswith("study_design.") or semantic in {
        "statistics.interim",
        "statistics.multiplicity",
        "safety.aesi",
    }:
        artifacts.insert(0, "synopsis")
    if semantic.startswith("statistics."):
        artifacts.append("statistics")
    if semantic.startswith(("procedures_assessments.", "intervention.")):
        artifacts.append("schedule")
    return list(dict.fromkeys(artifacts))


def _module_source_fact_ids(
    definition: Any,
    node: MedicalWritingProtocolTemplateNode,
) -> list[str]:
    prefix = f"study_definition:{definition.definition_id}:r{definition.revision}:"
    paths = {
        path
        for rule in node.applicability_rules
        for path in _FACET_SOURCE_PATHS.get(rule, ())
    }
    return [prefix + path for path in sorted(paths)]


def _missing_rule_is_explicitly_not_applicable(
    definition: Any,
    node: MedicalWritingProtocolTemplateNode,
    design_projection: Any = None,
) -> bool:
    design_projection = _consumer_design_projection(
        definition, design_projection
    )
    design_view = (
        design_projection.design_view if design_projection is not None else None
    )
    phase = _normalized_phase(
        design_view.study_phase
        if design_view is not None
        else getattr(definition.framing, "study_phase", "")
    )
    rules = set(node.applicability_rules)
    phase_rules = {rule for rule in rules if rule.startswith("phase:")}
    if phase and phase_rules and f"phase:{phase}" not in phase_rules:
        return True
    if any(rule.startswith("phase1:") for rule in rules):
        if design_view is not None:
            selected_codes = {
                str(part.part_code).strip().lower().replace("-", "_")
                for part in design_view.phase1_parts
            }
            facet_codes = {
                "phase1:sad": {"sad"},
                "phase1:mad": {"mad"},
                "phase1:food_effect": {"food_effect"},
                "phase1:special_population": {
                    "hepatic_impairment",
                    "renal_impairment",
                    "mass_balance",
                },
            }
            if any(
                rule in facet_codes
                and not (selected_codes & facet_codes[rule])
                for rule in rules
                if rule.startswith("phase1:")
            ):
                return True
        state = getattr(definition, "field_states", {}).get(
            "framing.intrinsic_objectives"
        )
        if state and state.status in {"confirmed", "not_applicable"}:
            return True
    if "feature:interim_analysis" in rules:
        structured_design = getattr(definition.framing, "structured_design", None)
        structured_interim = (
            design_view.interim_analysis
            if design_view is not None
            else getattr(structured_design, "interim_analysis", None)
        )
        if getattr(structured_interim, "planned", None) is False:
            return True
        if getattr(structured_interim, "planned", None) is True:
            return False
        if design_view is not None:
            return False
        text = " ".join(
            [
                getattr(definition.framing, "design_pattern", ""),
                getattr(definition.picos, "statistical_strategy", ""),
            ]
        )
        return bool(
            re.search(
                r"不(?:设置|进行|开展|实施)(?:正式)?期中|无(?:正式)?期中分析|"
                r"未计划(?:进行|开展|实施)?期中|"
                r"(?:no|without)\s+(?:formal\s+)?interim|"
                r"interim\s+analysis\s+(?:is\s+)?not\s+planned",
                text.lower(),
            )
        )
    if "feature:multiplicity" in rules:
        return _explicitly_excludes_multiplicity_control(
            getattr(definition.picos, "statistical_strategy", "")
        )
    if "feature:subgroup" in rules:
        return _explicitly_excludes_subgroup_analysis(
            getattr(definition.picos, "statistical_strategy", "")
        )
    if "design:randomized" in rules or "design:blinded" in rules:
        if design_view is not None:
            if (
                "design:randomized" in rules
                and design_view.randomization_mode == "non_randomized"
            ):
                return True
            if (
                "design:blinded" in rules
                and design_view.blinding_mode == "open_label"
            ):
                return True
            return False
        state = getattr(definition, "field_states", {}).get("framing.design_pattern")
        return bool(state and state.status == "confirmed")
    if "feature:safety_committee" in rules and design_view is not None:
        return (
            design_view.src_planned is False
            and design_view.dmc_planned is False
        )
    if "feature:immunogenicity" in rules:
        product = getattr(definition.framing, "product_profile", None)
        return (
            getattr(product, "technology_type", "unknown") == "small_molecule"
            and getattr(product, "immunogenicity_relevance", "unknown")
            == "not_expected"
        )
    for rule in rules:
        for path in _FACET_SOURCE_PATHS.get(rule, ()):
            state = getattr(definition, "field_states", {}).get(path)
            if state and state.status == "not_applicable":
                return True
    return False


def _missing_rule_is_deferred(
    definition: Any,
    node: MedicalWritingProtocolTemplateNode,
) -> bool:
    for rule in node.applicability_rules:
        for path in _FACET_SOURCE_PATHS.get(rule, ()):
            state = getattr(definition, "field_states", {}).get(path)
            if state and state.status == "deferred":
                return True
    return False


def _engine_module_resolution(
    definition: Any,
    node: MedicalWritingProtocolTemplateNode,
    facets: set[str],
    design_projection: Any = None,
) -> MedicalWritingProtocolModuleResolution:
    explicit = getattr(definition, "module_resolutions", {}).get(
        node.semantic_node_id
    )
    if explicit is not None:
        if not isinstance(explicit, MedicalWritingProtocolModuleResolution):
            explicit = MedicalWritingProtocolModuleResolution.model_validate(explicit)
        return explicit.model_copy(
            update={
                "template_node_id": node.node_id,
                "semantic_node_id": node.semantic_node_id,
                "resolution_source": "user_override",
                "user_override": True,
                "affected_artifacts": _module_affected_artifacts(node),
            },
            deep=True,
        )
    if node.applicability_mode == "required" or not node.applicability_rules:
        return MedicalWritingProtocolModuleResolution(
            template_node_id=node.node_id,
            semantic_node_id=node.semantic_node_id,
            status="applicable",
            render_action="retain_full",
            resolution_source="template_required",
            rationale="公司方案模板稳定核心章节。",
            affected_artifacts=_module_affected_artifacts(node),
        )
    source_fact_ids = _module_source_fact_ids(definition, node)
    if _company_node_is_applicable(node, facets):
        return MedicalWritingProtocolModuleResolution(
            template_node_id=node.node_id,
            semantic_node_id=node.semantic_node_id,
            status="applicable",
            render_action="retain_full",
            resolution_source="deterministic_rule",
            rationale="已确认的研究设计满足章节适用条件。",
            source_fact_ids=source_fact_ids,
            affected_artifacts=_module_affected_artifacts(node),
        )
    if _missing_rule_is_explicitly_not_applicable(
        definition, node, design_projection
    ):
        render_action = (
            "retain_not_applicable"
            if node.semantic_node_id in _RETAIN_NA_SEMANTIC_NODES
            else "omit"
        )
        return MedicalWritingProtocolModuleResolution(
            template_node_id=node.node_id,
            semantic_node_id=node.semantic_node_id,
            status="not_applicable",
            render_action=render_action,
            resolution_source="deterministic_rule",
            rationale="已确认的研究设计不包含该模块。",
            source_fact_ids=source_fact_ids,
            affected_artifacts=_module_affected_artifacts(node),
        )
    status = "deferred" if _missing_rule_is_deferred(definition, node) else "unknown"
    return MedicalWritingProtocolModuleResolution(
        template_node_id=node.node_id,
        semantic_node_id=node.semantic_node_id,
        status=status,
        render_action="omit",
        resolution_source="deterministic_rule",
        rationale=(
            "该设计决定已延期，待项目团队明确后再生成相关章节。"
            if status == "deferred"
            else "现有项目事实不足以确定该章节是否适用。"
        ),
        source_fact_ids=source_fact_ids,
        affected_artifacts=_module_affected_artifacts(node),
    )


def _company_module_resolutions(
    template: MedicalWritingProtocolTemplateDefinition,
    definition: Any,
    design_projection: Any = None,
) -> list[MedicalWritingProtocolModuleResolution]:
    facets = _project_facets(definition, design_projection)
    return [
        _engine_module_resolution(
            definition, node, facets, design_projection
        )
        for node in template.nodes
    ]


def _selected_company_nodes(
    template: MedicalWritingProtocolTemplateDefinition,
    definition: Any,
    design_projection: Any = None,
) -> list[MedicalWritingProtocolTemplateNode]:
    resolutions = {
        item.template_node_id: item
        for item in _company_module_resolutions(
            template, definition, design_projection
        )
    }
    selected_ids = {
        node_id
        for node_id, resolution in resolutions.items()
        if resolution.render_action != "omit"
    }
    return [
        node
        for node in template.nodes
        if node.node_id in selected_ids
        and (not node.parent_node_id or node.parent_node_id in selected_ids)
    ]


def _continuous_section_numbers(
    nodes: list[MedicalWritingProtocolTemplateNode],
) -> dict[str, str]:
    children: dict[str, list[MedicalWritingProtocolTemplateNode]] = {}
    for node in nodes:
        if node.section_number:
            children.setdefault(node.parent_node_id, []).append(node)
    numbers: dict[str, str] = {}

    def visit(parent_id: str, prefix: str = "") -> None:
        for index, child in enumerate(children.get(parent_id, []), start=1):
            number = f"{prefix}.{index}" if prefix else str(index)
            numbers[child.node_id] = number
            visit(child.node_id, number)

    visit("")
    return numbers


def _joined(values: Any) -> str:
    if isinstance(values, list):
        return "；".join(
            part
            for item in values
            for part in [_joined(item)]
            if part
        )
    if isinstance(values, dict):
        parts = []
        for key, item in values.items():
            text = _joined(item)
            if text:
                parts.append(f"{key}={text}" if key else text)
        return "；".join(parts)
    if hasattr(values, "model_dump"):
        try:
            dumped = values.model_dump(mode="json")
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            preferred = []
            for key in (
                "technology_type",
                "route_of_administration",
                "dosage_form",
                "mechanism_summary",
                "exposure_summary",
                "label",
                "summary",
            ):
                text = str(dumped.get(key) or "").strip()
                if text:
                    preferred.append(text)
            if preferred:
                return "；".join(preferred)
            return _joined(dumped)
    return str(values or "").strip()


def _mentions_planned_interim_analysis(*values: Any) -> bool:
    text = " ".join(str(value or "").strip() for value in values).lower()
    if not any(term in text for term in ("期中", "interim")):
        return False
    negative_patterns = (
        r"不(?:设置|进行|开展|实施)(?:正式)?期中",
        r"无(?:正式)?期中分析",
        r"未计划(?:进行|开展|实施)?期中",
        r"(?:no|without)\s+(?:formal\s+)?interim",
        r"interim\s+analysis\s+(?:is\s+)?not\s+planned",
    )
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return False
    positive_patterns = (
        r"(?:设置|计划|拟|将|开展|实施|进行).{0,18}期中分析",
        r"期中分析.{0,12}(?:将在|计划|拟于|实施|开展|进行)",
        r"(?:planned|conduct|perform|implement).{0,24}interim",
        r"interim.{0,24}(?:planned|will\s+be\s+conducted|will\s+be\s+performed)",
    )
    return any(re.search(pattern, text) for pattern in positive_patterns)


def _mentions_planned_multiplicity_control(*values: Any) -> bool:
    text = " ".join(str(value or "").strip() for value in values).lower()
    if _explicitly_excludes_multiplicity_control(text):
        return False
    terms = (
        "多重性",
        "多重检验",
        "α分配",
        "α消耗",
        "alpha分配",
        "alpha allocation",
        "alpha spending",
        "multiplicity",
        "multiple testing",
        "gatekeeping",
        "闭合检验",
        "序贯检验",
        "层级检验",
        "hierarchical testing",
        "hochberg",
        "holm",
        "bonferroni",
    )
    return any(term in text for term in terms)


def _explicitly_excludes_multiplicity_control(*values: Any) -> bool:
    text = " ".join(str(value or "").strip() for value in values).lower()
    patterns = (
        r"不(?:进行|设置|采用|考虑).{0,12}(?:多重性|多重检验|α分配|alpha分配)",
        r"(?:多重性|多重检验).{0,12}(?:不调整|不校正|不控制|不适用)",
        r"(?:no|without)\s+(?:formal\s+)?(?:multiplicity|multiple[- ]testing)",
        r"(?:multiplicity|multiple[- ]testing).{0,20}(?:not\s+planned|not\s+applicable|not\s+adjusted)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _mentions_planned_subgroup_analysis(*values: Any) -> bool:
    text = " ".join(str(value or "").strip() for value in values).lower()
    if _explicitly_excludes_subgroup_analysis(text):
        return False
    positive_patterns = (
        r"(?:预设|预先规定|计划|拟|将).{0,18}亚组分析",
        r"亚组分析.{0,18}(?:预设|预先规定|计划|拟开展|将进行)",
        r"(?:prespecified|pre[- ]specified|planned).{0,18}subgroup",
        r"subgroup.{0,18}(?:prespecified|pre[- ]specified|planned)",
    )
    return any(re.search(pattern, text) for pattern in positive_patterns)


def _explicitly_excludes_subgroup_analysis(*values: Any) -> bool:
    text = " ".join(str(value or "").strip() for value in values).lower()
    patterns = (
        r"不(?:进行|设置|开展|计划|预设).{0,12}亚组分析",
        r"无(?:预设|预先规定)?亚组分析",
        r"亚组分析.{0,12}(?:不进行|不设置|不适用|未计划)",
        r"(?:no|without)\s+(?:prespecified\s+|planned\s+)?subgroup",
        r"subgroup\s+analys(?:is|es).{0,20}(?:not\s+planned|not\s+applicable)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _bullet_rich_text(values: Any) -> dict[str, Any]:
    items = _protocol_list_items(values)
    return {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "attrs": {
                                    "stylePreset": "body",
                                    "firstLineIndentChars": 0,
                                },
                                "content": [{"type": "text", "text": item}],
                            }
                        ],
                    }
                    for item in items
                ],
            }
        ],
    }


def _endpoint_rich_text(values: Any) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    pending_items: list[str] = []

    def flush_items() -> None:
        if not pending_items:
            return
        content.append(_bullet_rich_text(list(pending_items))["content"][0])
        pending_items.clear()

    for item in _protocol_list_items(values):
        if re.search(r"(?:目的|终点|endpoint)\s*[：:]$", item, re.IGNORECASE):
            flush_items()
            content.append(
                {
                    "type": "paragraph",
                    "attrs": {
                        "stylePreset": "body",
                        "firstLineIndentChars": 0,
                    },
                    "content": [
                        {
                            "type": "text",
                            "text": item,
                            "marks": [{"type": "bold"}],
                        }
                    ],
                }
            )
            continue
        pending_items.append(
            re.sub(r"^\s*(?:[（(]?\d+[）).、]|[①②③④⑤⑥⑦⑧⑨⑩])\s*", "", item)
        )
    flush_items()
    return {"type": "doc", "content": content}


def _protocol_list_items(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else [values]
    items: list[str] = []
    for raw_value in raw_values:
        for item in re.split(r"[\r\n]+", str(raw_value or "")):
            normalized = item.strip()
            if normalized:
                items.append(normalized)
    return items


def _objective_for_endpoint(
    *,
    product: str,
    population: str,
    endpoint: str,
    objective_type: str,
) -> str:
    if not endpoint:
        return f"待根据已确认的{objective_type}终点生成并确认{objective_type}目的。"
    target = population or "目标研究人群"
    focus = _objective_focus_for_endpoint(endpoint)
    return f"评价{product or '研究药物'}在{target}中的{focus}。"


def _objective_focus_for_endpoint(
    endpoint: str,
    *,
    default_focus: str = "有效性",
) -> str:
    normalized = endpoint.lower()
    if any(item in normalized for item in ("安全", "耐受", "ae", "sae", "aesi")):
        return "安全性和耐受性"
    if any(
        item in normalized
        for item in ("暴露-效应", "暴露–效应", "暴露—效应", "e-r", "exposure-response")
    ):
        return "暴露-效应关系"
    if any(item in normalized for item in ("pk", "药代", "血药浓度", "暴露量")):
        return "药代动力学特征"
    if any(
        item in normalized
        for item in (
            "pd",
            "药效动力学",
            "药效",
            "机制性指标",
            "机制性生物标志物",
            "生物标志物",
            "biomarker",
            "补体",
            "wieslab",
            "ah50",
            "bb",
            "c3",
            "克隆",
        )
    ):
        return "药效动力学特征"
    return default_focus


def _objectives_for_endpoints(
    *,
    product: str,
    population: str,
    endpoints: Any,
    objective_type: str,
) -> list[str]:
    endpoint_items = [
        item
        for item in _protocol_list_items(endpoints)
        if not re.search(r"(?:目的|终点|endpoint)\s*[：:]$", item, re.IGNORECASE)
    ]
    if not endpoint_items:
        return [
            _objective_for_endpoint(
                product=product,
                population=population,
                endpoint="",
                objective_type=objective_type,
            )
        ]
    target = population or "目标研究人群"
    default_focus = "探索性指标" if objective_type == "探索性" else "有效性"
    focuses = list(
        dict.fromkeys(
            _objective_focus_for_endpoint(
                endpoint,
                default_focus=default_focus,
            )
            for endpoint in endpoint_items
        )
    )
    return [
        f"评价{product or '研究药物'}在{target}中的{focus}。"
        for focus in focuses
    ]


# Deterministic mapping from company body chapter semantic_node_id to the
# ordered StudyDefinition field paths that populate that chapter's initial
# draft. Only fields whose ``field_states`` status is ``confirmed`` are
# projected; ``not_applicable`` fields never contribute their stale clinical
# values to an otherwise applicable chapter (module-level
# ``retain_not_applicable`` remains a separate path that writes an explicit
# 不适用 paragraph). Values are rendered verbatim and never transformed,
# merged across projects, or numerically altered. Chapters absent from this
# mapping either have a specialised projector above (synopsis,
# study_design.overall, procedures_assessments.efficacy) or remain candidates
# for downstream drafting. Missing content is represented by typed readiness
# metadata on the section seed rather than prose in the body.
_CHAPTER_BODY_FACT_PATHS: dict[str, tuple[str, ...]] = {
    "background.disease": ("framing.indication",),
    "background": (
        "framing.indication",
        "framing.investigational_product",
        "framing.population_intent",
        "framing.intrinsic_objectives",
    ),
    "background.mechanism": (
        "framing.investigational_product",
        "framing.product_profile",
        "picos.intervention_summary",
    ),
    "background.benefit_risk": (
        "framing.population_intent",
        "picos.safety_endpoints",
    ),
    "background.rationale": (
        "framing.target_mechanism",
        "framing.intrinsic_objectives",
    ),
    "background.product": ("framing.investigational_product",),
    "objectives_endpoints.primary": (
        "picos.primary_objectives",
        "picos.primary_endpoint",
    ),
    "objectives_endpoints.secondary": (
        "picos.secondary_objectives",
        "picos.key_secondary_endpoints",
        "picos.other_secondary_endpoints",
    ),
    "objectives_endpoints.exploratory": (
        "picos.exploratory_objectives",
        "picos.exploratory_endpoints",
    ),
    "study_design.rationale": (
        "picos.estimand_strategy",
    ),
    "study_design.randomization": ("framing.structured_design",),
    "study_design.blinding": ("framing.structured_design",),
    "study_design.study_end": ("picos.study_epochs",),
    "population.size": ("picos.sample_size_strategy",),
    "population.selection": (
        "framing.population_intent",
        "picos.population_summary",
    ),
    "population.inclusion": ("picos.inclusion_modules",),
    "population.exclusion": ("picos.exclusion_modules",),
    "intervention.product": ("framing.investigational_product",),
    "intervention.regimen": (
        "picos.intervention_summary",
        "picos.intervention_dose_regimen",
    ),
    "intervention.concomitant": (
        "picos.allowed_concomitant_rules",
        "picos.required_background_rules",
        "picos.prohibited_concomitant_rules",
    ),
    "intervention.concomitant_allowed": (
        "picos.allowed_concomitant_rules",
    ),
    "intervention.concomitant_prohibited": (
        "picos.prohibited_concomitant_rules",
    ),
    "intervention.background": ("picos.required_background_rules",),
    "statistics.sample_size": ("picos.sample_size_strategy",),
    "statistics.analysis_sets": ("picos.statistical_strategy",),
    "statistics.general": ("picos.statistical_strategy",),
    "statistics.efficacy": (
        "picos.statistical_strategy",
        "picos.primary_endpoint",
    ),
    "statistics.interim": (
        "framing.structured_design",
        "picos.statistical_strategy",
    ),
    "statistics.multiplicity": ("picos.statistical_strategy",),
    "safety.aesi": ("picos.aesi_definitions",),
    "safety.definitions": ("picos.safety_endpoints",),
}

def _project_chapter_body_draft(
    definition: Any,
    node: MedicalWritingProtocolTemplateNode,
    *,
    fact_prefix: str,
    confirmed_set: set[str],
    value_fn: Any,
) -> tuple[str, list[str]]:
    """Deterministically project confirmed facts into a chapter body draft.

    Returns ``(initial_text, source_fact_ids)``. Only field paths whose
    ``field_states`` status is ``confirmed`` are rendered; values are joined
    verbatim and never numerically transformed, re-grouped, or invented. When
    no confirmed fact is available, the body remains empty so the downstream
    greenfield drafting path can generate a candidate. Typed readiness
    metadata explains the block without polluting clinical prose.
    """

    paths = _CHAPTER_BODY_FACT_PATHS.get(node.semantic_node_id)
    if not paths:
        return "", []
    confirmed_values: list[str] = []
    confirmed_paths: list[str] = []
    for path in paths:
        if path not in confirmed_set:
            continue
        raw_value = value_fn(path)
        text = _joined(raw_value)
        if not text:
            continue
        confirmed_values.append(text)
        confirmed_paths.append(path)
    if confirmed_values:
        return "\n".join(confirmed_values), [
            fact_prefix + path for path in confirmed_paths
        ]
    return "", []


def _section_drafting_readiness(
    node: MedicalWritingProtocolTemplateNode,
    *,
    initial_text: str,
    initial_data: dict[str, Any],
    confirmed_set: set[str],
    has_selected_children: bool,
    applicability_status: str,
    applicability_render_action: str,
) -> dict[str, Any]:
    if (
        applicability_status == "not_applicable"
        or applicability_render_action == "retain_not_applicable"
    ):
        return {"drafting_status": "not_applicable"}
    if (
        initial_data
        or node.node_kind in {"front_matter", "glossary", "document_control"}
    ):
        return {"drafting_status": "structural_content"}
    normalized_text = initial_text.strip()
    if normalized_text and not normalized_text.startswith(("待补充", "待确认")):
        return {"drafting_status": "substantive_draft"}
    if has_selected_children:
        return {"drafting_status": "structural_container"}

    mapped_paths = _CHAPTER_BODY_FACT_PATHS.get(node.semantic_node_id, ())
    missing_inputs = [
        path for path in mapped_paths if path not in confirmed_set
    ]
    if not missing_inputs:
        missing_inputs = [
            f"支持“{node.title_zh}”的已确认项目事实或已绑定来源摘录"
        ]
    applicability_unknown = (
        applicability_status in {"unknown", "deferred"}
        or applicability_render_action == "retain_placeholder"
    )
    return {
        "drafting_status": "actionable_blocker",
        "drafting_blocker_code": (
            "module_applicability_confirmation_required"
            if applicability_unknown
            else "project_evidence_missing"
        ),
        "drafting_blocker_reason": (
            "该模块的适用性尚未由已确认研究设计解析。"
            if applicability_unknown
            else "当前已确认项目事实不足以形成可审阅的章节正文。"
        ),
        "drafting_missing_inputs": missing_inputs,
        "drafting_resolution_actions": [
            "由系统从已绑定资料和已确认研究事实生成本章节候选正文。",
            "仅将仍影响临床设计的未决事项汇总到跨章节审核队列供用户确认。",
        ],
    }


def _project_structured_design_synopsis_text(
    definition: Any,
    design_projection: Any = None,
) -> str:
    """Render the synopsis design row only from NormalizedDesignProjection."""

    compatibility_framing = None
    if design_projection is None:
        if (
            hasattr(definition, "framing")
            and hasattr(definition.framing, "structured_design")
        ):
            design_projection = normalize_study_design(definition)
        elif hasattr(definition, "framing"):
            return str(
                getattr(definition.framing, "design_pattern", "") or ""
            ).strip()
        else:
            compatibility_framing = definition
            structured_design = getattr(definition, "structured_design", None)
            design_projection = type(
                "_CompatibilityProjection",
                (),
                {"design_view": structured_design},
            )()
    structured = design_projection.design_view
    parts: list[str] = []
    randomization_label = {
        "randomized": "随机化",
        "non_randomized": "非随机化",
    }.get(structured.randomization_mode)
    if randomization_label:
        parts.append(
            f"{randomization_label}（{structured.randomization_details}）"
            if structured.randomization_details
            else randomization_label
        )
    blinding_label = {
        "open_label": "开放标签",
        "single_blind": "单盲",
        "double_blind": "双盲",
        "triple_blind": "三盲",
    }.get(structured.blinding_mode)
    if blinding_label:
        segment = blinding_label
        if structured.blinded_roles:
            segment += f"（盲态角色：{_joined(structured.blinded_roles)}）"
        elif structured.blinding_details:
            segment += f"（{structured.blinding_details}）"
        parts.append(segment)
    comparator_label = {
        "placebo": "安慰剂对照",
        "active": "阳性药对照",
        "none_or_dose_escalation": "无平行对照/剂量递增",
    }.get(structured.comparator_type)
    if comparator_label:
        parts.append(
            f"{comparator_label}（{structured.comparator_intervention}）"
            if structured.comparator_intervention
            else comparator_label
        )
    for value in (structured.assignment_model, structured.center_model):
        if value:
            parts.append(value)
    if structured.phase1_parts:
        part_labels = [
            item.part_label or item.part_code for item in structured.phase1_parts
        ]
        segment = "含" + _joined(part_labels) + "模块"
        if structured.phase1_sequence:
            segment += f"（{structured.phase1_sequence}）"
        parts.append(segment)
    if structured.treatment_switch.planned is True:
        switch = structured.treatment_switch
        parts.append(
            "治疗切换："
            + "；".join(
                filter(
                    None,
                    [
                        switch.trigger_or_timing,
                        switch.eligible_population,
                        f"转入{switch.destination_treatment}",
                    ],
                )
            )
        )
    if structured.crossover.planned is True:
        crossover = structured.crossover
        parts.append(
            "交叉设计："
            + "；".join(
                filter(
                    None,
                    [
                        f"序列{_joined(crossover.sequences)}",
                        f"周期{_joined(crossover.periods)}",
                        crossover.washout_strategy,
                    ],
                )
            )
        )
    if structured.open_label_extension.planned is True:
        extension = structured.open_label_extension
        parts.append(
            "开放标签延展："
            + "；".join(
                filter(
                    None,
                    [
                        extension.entry_source,
                        extension.treatment_regimen,
                        extension.duration,
                    ],
                )
            )
        )
    if structured.sample_size_reestimation.planned is True:
        ssr = structured.sample_size_reestimation
        mode = "盲态" if ssr.reestimation_mode == "blinded" else "非盲态"
        parts.append(
            f"{mode}样本量再估计（{ssr.timing_or_information}；"
            f"{ssr.reestimated_parameter}）"
        )
    if structured.adaptive_design.planned is True:
        adaptive = structured.adaptive_design
        adaptive_label = {
            "seamless_phase": "无缝II/III期适应性设计",
            "group_sequential": "组序贯适应性设计",
            "sample_size_reestimation": "样本量再估计适应性设计",
        }.get(adaptive.adaptive_type, "适应性设计")
        parts.append(
            adaptive_label
            + (
                f"（{adaptive.adaptation_timing}；"
                f"{_joined(adaptive.adaptable_elements)}）"
                if adaptive.adaptation_timing
                else ""
            )
        )
    if structured.src_planned is True:
        parts.append("设置安全性审查委员会（SRC）")
    if structured.dmc_planned is True:
        parts.append("设置独立数据监查委员会（DMC）")
    rendered = "；".join(part for part in parts if part)
    if not rendered and compatibility_framing is not None:
        return str(
            getattr(compatibility_framing, "design_pattern", "") or ""
        ).strip()
    return rendered


def _project_interim_analysis_synopsis_value(
    design_projection: Any, picos: Any
) -> str | None:
    """Project the interim analysis synopsis row from structured facts.

    Returns the synopsis cell text when the interim chapter should appear,
    or None when the row should be omitted. Prefers the structured
    interim_analysis fact; falls back to legacy statistical_strategy text
    only when the structured planned status is undecided.
    """
    legacy_compatibility_call = not hasattr(design_projection, "design_view")
    if not legacy_compatibility_call:
        interim = design_projection.design_view.interim_analysis
    else:
        interim = getattr(
            getattr(design_projection, "structured_design", None),
            "interim_analysis",
            None,
        )
    planned = getattr(interim, "planned", None)
    if planned is False:
        return None
    statistical_text = str(getattr(picos, "statistical_strategy", "") or "").strip()
    if planned is True:
        detail_parts: list[str] = []
        for label, attr in (
            ("分析目的", "purpose"),
            ("实施时间", "timing"),
            ("信息分数", "information_fraction"),
            ("统计边界", "statistical_boundary"),
            ("α控制", "alpha_control"),
            ("独立委员会", "independent_committee"),
            ("操作防火墙", "operational_firewall"),
        ):
            value = str(getattr(interim, attr, "") or "").strip()
            if value:
                detail_parts.append(f"{label}：{value}")
        notes = str(getattr(interim, "notes", "") or "").strip()
        if notes:
            detail_parts.append(notes)
        if detail_parts:
            return "；".join(detail_parts)
        return statistical_text or "计划期中分析（具体统计细节待确认）。"
    # planned is undecided/None: allow statistical_strategy text as evidence,
    # whether or not a NormalizedDesignProjection wrapper is present.
    design_pattern = (
        getattr(design_projection, "design_pattern", "")
        if legacy_compatibility_call
        else ""
    )
    if statistical_text and _mentions_planned_interim_analysis(
        statistical_text,
        design_pattern,
    ):
        return statistical_text
    return None


def _company_synopsis_data(
    definition: Any,
    design_projection: Any,
) -> dict[str, Any]:
    framing = definition.framing
    picos = definition.picos
    product_profile = getattr(framing, "product_profile", None)
    product = getattr(framing, "investigational_product", "")
    population = getattr(picos, "population_summary", "") or getattr(
        framing, "population_intent", ""
    )
    secondary_endpoints = _protocol_list_items([
        *(getattr(picos, "key_secondary_endpoints", []) or []),
        *(getattr(picos, "other_secondary_endpoints", []) or []),
        *(getattr(picos, "safety_endpoints", []) or []),
    ])
    exploratory_endpoints = _protocol_list_items(
        getattr(picos, "exploratory_endpoints", []) or []
    )
    primary_endpoint = getattr(picos, "primary_endpoint", "")
    primary_endpoint_items = _protocol_list_items([primary_endpoint])
    secondary_text = "\n".join(secondary_endpoints)
    exploratory_text = "\n".join(exploratory_endpoints)
    primary_objectives = _protocol_list_items(
        getattr(picos, "primary_objectives", []) or []
    ) or _objectives_for_endpoints(
        product=product,
        population=population,
        endpoints=primary_endpoint_items,
        objective_type="主要",
    )
    secondary_objectives = _protocol_list_items(
        getattr(picos, "secondary_objectives", []) or []
    ) or _objectives_for_endpoints(
        product=product,
        population=population,
        endpoints=secondary_endpoints,
        objective_type="次要",
    )
    exploratory_objective_evidence = [
        *exploratory_endpoints,
        *(getattr(product_profile, "pk_pd_considerations", []) or []),
    ]
    exploratory_objectives = _protocol_list_items(
        getattr(picos, "exploratory_objectives", []) or []
    ) or _objectives_for_endpoints(
        product=product,
        population=population,
        endpoints=exploratory_objective_evidence,
        objective_type="探索性",
    )
    concomitant_parts = []
    for label, values in (
        ("允许的合并用药/治疗", getattr(picos, "allowed_concomitant_rules", []) or []),
        ("必须使用的背景治疗", getattr(picos, "required_background_rules", []) or []),
        ("禁止的合并用药/治疗", getattr(picos, "prohibited_concomitant_rules", []) or []),
    ):
        if values:
            concomitant_parts.append(f"{label}：{_joined(values)}")
    population_rules = []
    if getattr(picos, "inclusion_modules", []):
        population_rules.append(
            "入选标准：" + _joined(getattr(picos, "inclusion_modules", []))
        )
    if getattr(picos, "exclusion_modules", []):
        population_rules.append(
            "排除标准：" + _joined(getattr(picos, "exclusion_modules", []))
        )
    product_details = [product]
    if getattr(product_profile, "dosage_forms", []):
        product_details.append(
            "剂型：" + _joined(getattr(product_profile, "dosage_forms", []))
        )
    if getattr(product_profile, "administration_routes", []):
        product_details.append(
            "给药途径："
            + _joined(getattr(product_profile, "administration_routes", []))
        )
    rows = [
        {
            "label": "研究题目",
            "values": [getattr(framing, "document_title", "")],
            "merge_content": True,
        },
        {
            "label": "试验分期",
            "values": [getattr(framing, "study_phase", "")],
            "merge_content": True,
        },
        {"label": "研究对象", "values": [population], "merge_content": True},
        {
            "label": "目的与估计目标/终点",
            "values": ["主要目的", "相应的研究终点"],
            "style_role": "section_header",
            "nested_group_id": "objectives_endpoints",
            "nested_group_start": True,
            "nested_group_row_span": 6,
            "nested_section_type": "primary",
        },
        {
            "label": "目的与估计目标/终点",
            "values": [
                _joined(primary_objectives),
                primary_endpoint,
            ],
            "rich_values": [
                _bullet_rich_text(primary_objectives),
                _endpoint_rich_text(primary_endpoint_items),
            ],
            "nested_group_id": "objectives_endpoints",
            "nested_group_continuation": True,
            "nested_section_type": "primary",
        },
        {
            "label": "目的与估计目标/终点",
            "values": ["次要目的", "相应的研究终点"],
            "style_role": "section_header",
            "nested_group_id": "objectives_endpoints",
            "nested_group_continuation": True,
            "nested_section_type": "secondary",
        },
        {
            "label": "目的与估计目标/终点",
            "values": [
                _joined(secondary_objectives),
                secondary_text,
            ],
            "rich_values": [
                _bullet_rich_text(secondary_objectives),
                _endpoint_rich_text(secondary_endpoints),
            ],
            "nested_group_id": "objectives_endpoints",
            "nested_group_continuation": True,
            "nested_section_type": "secondary",
        },
        {
            "label": "目的与估计目标/终点",
            "values": ["探索性目的", "相应的研究终点"],
            "style_role": "section_header",
            "nested_group_id": "objectives_endpoints",
            "nested_group_continuation": True,
            "nested_section_type": "exploratory",
        },
        {
            "label": "目的与估计目标/终点",
            "values": [
                _joined(exploratory_objectives),
                exploratory_text,
            ],
            "rich_values": [
                _bullet_rich_text(exploratory_objectives),
                _endpoint_rich_text(exploratory_endpoints),
            ],
            "nested_group_id": "objectives_endpoints",
            "nested_group_continuation": True,
            "nested_section_type": "exploratory",
        },
        {
            "label": "研究设计",
            "values": [
                _project_structured_design_synopsis_text(
                    definition, design_projection
                )
            ],
            "merge_content": True,
        },
        {"label": "试验人群", "values": ["\n".join(population_rules)], "merge_content": True},
        {
            "label": "重新筛选",
            "values": ["待根据筛选失败原因、可纠正性和筛选期时间窗确认。"],
            "merge_content": True,
        },
        {"label": "研究药物", "values": ["\n".join(filter(None, product_details))], "merge_content": True},
        {
            "label": "研究干预",
            "values": [
                "\n".join(
                    filter(
                        None,
                        [
                            getattr(picos, "intervention_summary", ""),
                            getattr(picos, "intervention_dose_regimen", ""),
                        ],
                    )
                )
            ],
            "merge_content": True,
        },
        {
            "label": "提前终止治疗/退出研究",
            "values": ["待根据暂停、恢复、永久停药、退出研究和失访规则确认。"],
            "merge_content": True,
        },
        {
            "label": "合并/禁止用药或治疗",
            "values": ["\n".join(concomitant_parts)],
            "merge_content": True,
        },
        {
            "label": "样本量",
            "values": [getattr(picos, "sample_size_strategy", "")],
            "merge_content": True,
        },
        {
            "label": "统计分析",
            "values": [getattr(picos, "statistical_strategy", "")],
            "merge_content": True,
        },
    ]
    # P0 defines the stable relation and topic order. P1/P2 add project-type
    # modules only when the confirmed design requires them; the synopsis is
    # therefore not a universal fixed 18-row table.
    design_view = (
        design_projection.design_view
        if design_projection is not None
        else None
    )
    phase = _normalized_phase(
        design_view.study_phase
        if design_view is not None
        else getattr(framing, "study_phase", "")
    )
    if phase == "1":
        # Prefer projection Parts; else typed structured_design only.
        # Do not fall back to free-text intrinsic_objectives (dual authority).
        if design_view is not None:
            subtype_terms = [
                item.part_label or item.part_code
                for item in design_view.phase1_parts
            ]
        else:
            structured_parts = list(
                getattr(
                    getattr(framing, "structured_design", None),
                    "phase1_parts",
                    None,
                )
                or []
            )
            subtype_terms = [
                (getattr(part, "part_label", None) or getattr(part, "part_code", "") or "")
                for part in structured_parts
            ]
            subtype_terms = [term for term in subtype_terms if str(term).strip()]
        rows.insert(
            10,
            {
                "label": "I期研究组成",
                "values": [
                    _joined(subtype_terms)
                    or "待根据FIH/SAD/MAD及其他I期研究类型确认研究组成。"
                ],
                "merge_content": True,
            },
        )
        dose_basis = _joined(
            getattr(product_profile, "pharmacology_considerations", []) or []
        )
        rows.insert(
            15,
            {
                "label": "剂量设置依据",
                "values": [
                    dose_basis
                    or "待结合非临床、既往临床、PK/PD及安全性资料确认。"
                ],
                "merge_content": True,
            },
        )
    study_epochs = getattr(picos, "study_epochs", []) or []
    if study_epochs:
        rows.insert(
            11,
            {"label": "研究周期", "values": [_joined(study_epochs)], "merge_content": True},
        )
    estimand_strategy = getattr(picos, "estimand_strategy", "")
    estimand_state = getattr(definition, "field_states", {}).get(
        "picos.estimand_strategy"
    )
    # Synopsis follows the same confirmed-only projection rule as body seeds:
    # not_applicable/unknown/deferred estimands must not surface stale text.
    if estimand_strategy and (
        estimand_state is None or estimand_state.status == "confirmed"
    ):
        rows.insert(
            9,
            {"label": "估计目标", "values": [estimand_strategy], "merge_content": True},
        )
    interim_override = getattr(definition, "module_resolutions", {}).get(
        "statistics.interim"
    )
    interim_override_applicable = bool(
        interim_override
        and getattr(interim_override, "status", None) == "applicable"
        and getattr(interim_override, "render_action", None) == "retain_full"
    )
    interim_synopsis_value = _project_interim_analysis_synopsis_value(
        design_projection if design_projection is not None else framing,
        picos,
    )
    if interim_override_applicable or interim_synopsis_value is not None:
        rows.insert(
            len(rows) - 1,
            {
                "label": "期中分析",
                "values": [
                    interim_synopsis_value
                    if interim_synopsis_value is not None
                    else getattr(picos, "statistical_strategy", "")
                ],
                "merge_content": True,
            },
        )
    objective_endpoint_subtable = {
        "group_id": "objectives_endpoints",
        "label": "目的与估计目标/终点",
        "columns": ["目的", "相应的研究终点"],
        "sections": [
            {
                "section_type": "primary",
                "label": "主要目的",
                "objectives": primary_objectives,
                "endpoints": primary_endpoint_items,
            },
            {
                "section_type": "secondary",
                "label": "次要目的",
                "objectives": secondary_objectives,
                "endpoints": secondary_endpoints,
            },
            {
                "section_type": "exploratory",
                "label": "探索性目的",
                "objectives": exploratory_objectives,
                "endpoints": exploratory_endpoints,
            },
        ],
    }
    return {
        "schema_version": "cms_protocol_synopsis_v1",
        "authority_source_id": CMS_D017_PNH_SYNOPSIS,
        "columns": ["项目", "目的/内容", "相应的研究终点"],
        "nested_groups": [objective_endpoint_subtable],
        "rows": rows,
    }


class MedicalWritingProtocolTemplateService:
    def __init__(
        self,
        plan_consumption_helper: Any = None,
    ) -> None:
        """Optional ``plan_consumption_helper`` for confirmed-plan projection.

        When injected, synopsis and section/module resolution consume one
        confirmed current plan revision (projections ``synopsis`` and
        ``sections_toc``).  If the plan is missing, unconfirmed, stale, or has
        unresolved blocking drivers, the helper raises ``PlanConsumptionError``
        and design-driven content fails closed.
        """
        self._plan_helper = plan_consumption_helper

    def _require_plan_projection(
        self,
        project_id: str,
        projection_kind: str,
    ) -> Any:
        """Return the confirmed plan state for *projection_kind* or ``None``.

        When no helper is injected, returns ``None`` (backward-compatible for
        tests that do not exercise plan consumption).  When the helper is
        present but the plan is missing/unconfirmed/stale, it raises
        ``PlanConsumptionError`` — the caller must let it propagate so the
        consumer fails closed.
        """
        if self._plan_helper is None:
            return None
        return self._plan_helper.require_confirmed_projection(
            project_id=project_id,
            projection_kind=projection_kind,
        )

    def _require_design_projection(
        self,
        definition: Any,
        projection_kind: str,
    ) -> Any:
        if self._plan_helper is None:
            return _consumer_design_projection(definition)
        state, current_definition, projection = (
            self._plan_helper.require_confirmed_design_projection(
                project_id=getattr(definition, "project_id", ""),
                projection_kind=projection_kind,
            )
        )
        del state
        supplied_identity = (
            getattr(definition, "definition_id", ""),
            getattr(definition, "revision", 0),
            getattr(definition, "state_sha256", ""),
        )
        current_identity = (
            current_definition.definition_id,
            current_definition.revision,
            current_definition.state_sha256,
        )
        if supplied_identity != current_identity:
            raise ValueError(
                "protocol template consumer received a StudyDefinition that "
                "does not match the confirmed plan"
            )
        return projection

    def definition(
        self,
        template_id: str = TEMPLATE_ID,
        template_version: str = TEMPLATE_VERSION,
    ) -> MedicalWritingProtocolTemplateDefinition:
        if template_id == TEMPLATE_ID and template_version == TEMPLATE_VERSION:
            metadata = {
                "authority": (
                    "公司中文临床试验方案模板族：D017-PNH方案摘要v0.2控制摘要内容、"
                    "格式和主题顺序；D017 I期、D001 II期及MG-K10 III期方案控制"
                    "全文稳定核心与分期模块"
                ),
                "effective_date": "2026-07-19",
                "lifecycle_status": "final",
                "china_regulatory_status": "effective",
                "china_applicability_rule": (
                    "公司权威方案优先；仅在公司参考冲突、M11规范更清晰且同类竞品"
                    "普遍覆盖时，M11才作为细节裁决依据。"
                ),
                "source_documents": [
                    {
                        "source_id": CMS_D017_PNH_SYNOPSIS,
                        "title": "CMS-D017-PNH-方案摘要_v0.2.docx",
                        "sha256": "d57a6950f701b4fe5cd80ea04a7541d9b3fd3b2f6a067980679253830e19faa0",
                        "authority_tier": "P0",
                    },
                    {
                        "source_id": CMS_D005_OBESITY_SYNOPSIS,
                        "title": "CMS-D005-减重II期临床试验方案概要-V0.3.docx",
                        "sha256": "4ba4b372d3be92faba978650158e71a1fb5945dffd2ee48a25b50b2d3a06adb7",
                        "authority_tier": "P1",
                    },
                    {
                        "source_id": MY004_RA_SYNOPSIS,
                        "title": "MY004-RA-2b 研究方案摘要_V0.3.docx",
                        "sha256": "f6c8fdf53535a58f0f05055fe07c3a34bb0932f30c8bc2a7cdb6f8fc97dc8be4",
                        "authority_tier": "P2",
                    },
                    {
                        "source_id": MY004_DERMATOLOGY_SYNOPSIS,
                        "title": "MY004567片-炎症性皮肤病-方案摘要-V0.4.docx",
                        "sha256": "4cfb22d281bb8bd90a863d565252a5481367a1bf165145f9151cf0dc3ac80fd9",
                        "authority_tier": "P2",
                    },
                    {
                        "source_id": CMS_D017_PHASE1_PROTOCOL,
                        "title": "CMS-D017Ⅰ期方案-v1.1-20260209-clean.docx",
                        "sha256": "0299282a5ac2d10749931ed0d06eecc7a4b3a1d912f395722553c0345055b1b5",
                        "authority_tier": "full_protocol_phase_1",
                    },
                    {
                        "source_id": CMS_D001_PHASE2_PROTOCOL,
                        "title": "CMD-D001-AD II期临床方案-V1.0.docx",
                        "sha256": "5fcbb6236947b5854df8c2f21dde7fc6fe22b9015cb955ee0f4a9c135c0e4b36",
                        "authority_tier": "full_protocol_phase_2",
                    },
                    {
                        "source_id": MGK10_PHASE3_PROTOCOL,
                        "title": "MG-K10-青少年AD-3期方案V1.0.docx",
                        "sha256": "c671644561ac48888fcf336d29df37029afe921bd07cff8433a59eae936e4560",
                        "authority_tier": "full_protocol_phase_3",
                    },
                ],
            }
            nodes = _company_nodes()
        elif template_id == M11_TEMPLATE_ID:
            registry = {
                DRAFT_TEMPLATE_VERSION: {
                    "chapters": _DRAFT_CHAPTERS,
                    "authority": "ICH M11 中文模板文件（2025-01-14，Stage 3 草案）",
                    "effective_date": "2025-01-14",
                    "lifecycle_status": "draft",
                    "china_regulatory_status": "historical_draft",
                    "china_applicability_rule": "历史草案，仅用于重放既有文档，不用于新建方案。",
                    "source_documents": [],
                },
                M11_TEMPLATE_VERSION: {
                    "chapters": _STEP4_CHAPTERS,
                    "authority": "ICH M11 2025-11-19第4阶段终版；采用国家药监局药审中心2026-06-12公开征求意见中文翻译稿作为中文结构参考",
                    "effective_date": "2025-11-19",
                    "lifecycle_status": "final",
                    "china_regulatory_status": "public_consultation",
                    "china_applicability_rule": "征求意见版实施建议拟规定：公告发布之日6个月后开始的相关临床试验，适用M11指导原则、技术规范及模板文件；正式公告前不得视为已生效规则。",
                    "source_documents": [
                        {"title": "M11指导原则中文版.pdf", "sha256": "93f8672cc8ca9105e81d3b01ff8202d9e7adb884b95515d0b3a4f3a867d80073"},
                        {"title": "M11技术规范中文版.pdf", "sha256": "2b5e669fd1be4d37b51e852290eb8974e11111d6e8c1e8080f1dd209f7407757"},
                        {"title": "M11模板中文版.pdf", "sha256": "6828ae564df1586af2d97669de02dce10f39f1905b03ab43c3e940820dac1b42"},
                        {"title": "M11指导原则及相关文件实施建议.pdf", "sha256": "17a18d84a57b642a9382a9cf9d97618598276e0c26dd1b11c568bfae3de7f05e"},
                    ],
                },
            }
            metadata = registry.get(template_version)
            if metadata is None:
                raise KeyError(
                    f"unsupported medical-writing protocol template: {template_id}/{template_version}"
                )
            nodes = _nodes(metadata["chapters"])
        else:
            raise KeyError(
                f"unsupported medical-writing protocol template: {template_id}/{template_version}"
            )
        definition_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "template_id": template_id,
                    "template_version": template_version,
                    "country": "CN",
                    "language": "zh-CN",
                    "effective_date": metadata["effective_date"],
                    "lifecycle_status": metadata["lifecycle_status"],
                    "china_regulatory_status": metadata["china_regulatory_status"],
                    "china_applicability_rule": metadata["china_applicability_rule"],
                    "source_documents": metadata["source_documents"],
                    "nodes": [node.model_dump(mode="json") for node in nodes],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return MedicalWritingProtocolTemplateDefinition(
            template_id=template_id,
            template_version=template_version,
            authority=metadata["authority"],
            country="CN",
            language="zh-CN",
            effective_date=metadata["effective_date"],
            lifecycle_status=metadata["lifecycle_status"],
            china_regulatory_status=metadata["china_regulatory_status"],
            china_applicability_rule=metadata["china_applicability_rule"],
            source_documents=metadata["source_documents"],
            definition_sha256=definition_sha256,
            nodes=nodes,
        )

    def section_seeds(
        self,
        definition: Any,
        template: MedicalWritingProtocolTemplateDefinition | None = None,
    ) -> list[MedicalWritingGreenfieldSectionSeed]:
        template = template or self.definition()
        # Consume one confirmed current plan revision for section applicability.
        # When the helper is injected, this fails closed on missing/unconfirmed/
        # stale/unresolved plans — no silent free-text re-infer of design-driven
        # chapters.
        design_projection = self._require_design_projection(
            definition, "sections_toc"
        )
        if template.template_id == TEMPLATE_ID:
            module_resolutions = _company_module_resolutions(
                template, definition, design_projection
            )
        else:
            module_resolutions = self.module_resolutions(definition, template)
        resolutions_by_node_id = {
            item.template_node_id: item for item in module_resolutions
        }
        if template.template_id == TEMPLATE_ID:
            selected_nodes = _selected_company_nodes(
                template, definition, design_projection
            )
        else:
            selected_nodes = [
                node
                for node in template.nodes
                if resolutions_by_node_id.get(node.node_id,
                    type("R", (), {"render_action": "retain_full"})(),
                ).render_action != "omit"
            ]
        selected_parent_node_ids = {
            node.parent_node_id for node in selected_nodes if node.parent_node_id
        }
        section_numbers = (
            _continuous_section_numbers(selected_nodes)
            if template.template_id == TEMPLATE_ID
            else {node.node_id: node.section_number for node in selected_nodes}
        )
        fact_prefix = f"study_definition:{definition.definition_id}:r{definition.revision}:"
        # Body/design fact projection admits only ``confirmed`` facts. Stale
        # values under ``not_applicable`` must never populate an applicable
        # chapter; module-level retain_not_applicable remains a separate path.
        confirmed = [
            path
            for path, state in definition.field_states.items()
            if state.status == "confirmed"
        ]
        confirmed_set = set(confirmed)
        design_paths = [
            "framing.population_intent",
            "picos.intervention_summary",
            "picos.comparator_summary",
            "picos.primary_endpoint",
        ]

        def value(path: str) -> Any:
            group, field = path.split(".", 1)
            return getattr(getattr(definition, group), field)

        selected_design = [path for path in design_paths if path in confirmed and str(value(path) or "").strip()]
        instrument_path = "picos.assessment_instruments"
        seeds: list[MedicalWritingGreenfieldSectionSeed] = []
        for node in selected_nodes:
            resolution = resolutions_by_node_id.get(node.node_id)
            heading = materialize_repeatable_objective_heading(
                node.title_zh,
                template_node_id=node.node_id,
            )
            initial_text = ""
            source_fact_ids: list[str] = []
            initial_data: dict[str, Any] = {}
            if node.node_kind == "protocol_synopsis":
                initial_text = definition.synopsis_text
                source_fact_ids = [fact_prefix + path for path in confirmed]
                if template.template_id == TEMPLATE_ID:
                    # Synopsis is a design-driven projection: consume the
                    # confirmed plan's synopsis projection or fail closed.
                    synopsis_projection = self._require_design_projection(
                        definition, "synopsis"
                    )
                    initial_data = _company_synopsis_data(
                        definition, synopsis_projection
                    )
            elif node.semantic_node_id in {"study_design.overall", "m11.4.1"}:
                initial_text = _project_structured_design_synopsis_text(
                    definition, design_projection
                )
                source_fact_ids = [
                    fact_prefix + "framing.structured_design"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "study_design.randomization"
            ):
                view = design_projection.design_view
                initial_text = (
                    "采用随机化分配。"
                    + (
                        f"{view.randomization_details}"
                        if view.randomization_details
                        else ""
                    )
                )
                source_fact_ids = [
                    fact_prefix
                    + "framing.structured_design.randomization_mode"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "study_design.blinding"
            ):
                view = design_projection.design_view
                label = {
                    "single_blind": "单盲",
                    "double_blind": "双盲",
                    "triple_blind": "三盲",
                }.get(view.blinding_mode, view.blinding_mode)
                initial_text = (
                    f"本研究采用{label}设计。"
                    + (view.blinding_details or "")
                )
                source_fact_ids = [
                    fact_prefix
                    + "framing.structured_design.blinding_mode"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "study_design.phase1_parts"
            ):
                initial_text = "；".join(
                    f"{part.part_label or part.part_code}："
                    f"{part.population}；{part.cohort_dose}"
                    for part in design_projection.design_view.phase1_parts
                )
                source_fact_ids = [
                    fact_prefix + "framing.structured_design.phase1_parts"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "study_design.safety_committee"
            ):
                view = design_projection.design_view
                committees = []
                if view.src_planned is True:
                    committees.append("设置安全性审查委员会（SRC）")
                if view.dmc_planned is True:
                    committees.append("设置独立数据监查委员会（DMC）")
                initial_text = "；".join(committees)
                source_fact_ids = [
                    fact_prefix + "framing.structured_design.src_planned",
                    fact_prefix + "framing.structured_design.dmc_planned",
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id
                in {
                    "intervention.regimen",
                    "procedures_assessments.treatment_followup",
                }
                and any(
                    item.planned is True
                    for item in (
                        design_projection.design_view.treatment_switch,
                        design_projection.design_view.crossover,
                        design_projection.design_view.open_label_extension,
                    )
                )
            ):
                view = design_projection.design_view
                details: list[str] = []
                paths: list[str] = []
                if view.crossover.planned is True:
                    details.append(
                        "交叉设计："
                        f"{'；'.join(view.crossover.sequences)}；"
                        f"{'；'.join(view.crossover.periods)}；"
                        f"{view.crossover.washout_strategy}；"
                        f"{view.crossover.period_sequence_analysis}"
                    )
                    paths.append(
                        "framing.structured_design.crossover"
                    )
                if view.treatment_switch.planned is True:
                    details.append(
                        "治疗切换："
                        f"{view.treatment_switch.trigger_or_timing}；"
                        f"{view.treatment_switch.eligible_population}转入"
                        f"{view.treatment_switch.destination_treatment}；"
                        f"{view.treatment_switch.blinding_strategy}；"
                        f"{view.treatment_switch.analysis_handling}"
                    )
                    paths.append(
                        "framing.structured_design.treatment_switch"
                    )
                if view.open_label_extension.planned is True:
                    details.append(
                        "开放标签延展："
                        f"{view.open_label_extension.entry_eligibility}；"
                        f"{view.open_label_extension.treatment_regimen}；"
                        f"{view.open_label_extension.duration}；"
                        f"{view.open_label_extension.blind_break_and_transition}"
                    )
                    paths.append(
                        "framing.structured_design.open_label_extension"
                    )
                initial_text = "\n".join(details)
                source_fact_ids = [fact_prefix + path for path in paths]
            elif (
                node.semantic_node_id == "intervention.background"
                and getattr(
                    definition.picos, "required_background_rules", None
                )
            ):
                initial_text = "；".join(
                    definition.picos.required_background_rules
                )
                source_fact_ids = [
                    fact_prefix + "picos.required_background_rules"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "statistics.interim"
            ):
                initial_text = (
                    _project_interim_analysis_synopsis_value(
                        design_projection, definition.picos
                    )
                    or ""
                )
                source_fact_ids = [
                    fact_prefix
                    + "framing.structured_design.interim_analysis"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "statistics.general"
                and design_projection.design_view.adaptive_design.planned
                is True
            ):
                adaptive = design_projection.design_view.adaptive_design
                initial_text = (
                    "采用适应性设计："
                    f"{adaptive.adaptive_type}；"
                    f"{adaptive.adaptation_timing}；"
                    f"{adaptive.decision_criteria}；"
                    f"可调整要素包括{'、'.join(adaptive.adaptable_elements)}；"
                    f"{adaptive.simulation_operating_characteristics}；"
                    f"{adaptive.type_i_error_control}；"
                    f"{adaptive.operational_control}"
                )
                source_fact_ids = [
                    fact_prefix + "framing.structured_design.adaptive_design"
                ]
            elif (
                design_projection is not None
                and node.semantic_node_id == "statistics.sample_size"
            ):
                ssr = design_projection.design_view.sample_size_reestimation
                if ssr.planned is True:
                    mode = (
                        "盲态"
                        if ssr.reestimation_mode == "blinded"
                        else "非盲态"
                    )
                    initial_text = (
                        f"计划进行{mode}样本量再估计："
                        f"{ssr.timing_or_information}；"
                        f"再估计参数为{ssr.reestimated_parameter}；"
                        f"决策规则为{ssr.decision_rule}；"
                        f"{ssr.alpha_protection}；{ssr.operational_protection}"
                    )
                    source_fact_ids = [
                        fact_prefix
                        + "framing.structured_design.sample_size_reestimation"
                    ]
            elif (
                node.semantic_node_id
                in {"procedures_assessments.efficacy", "m11.8.3"}
                and instrument_path in confirmed
            ):
                initial_text = render_assessment_instrument_methods(definition)
                if initial_text:
                    source_fact_ids = [fact_prefix + instrument_path]
            if (
                not initial_text
                and not source_fact_ids
                and template.template_id == TEMPLATE_ID
                and node.node_kind not in {"front_matter", "document_control"}
            ):
                body_text, body_fact_ids = _project_chapter_body_draft(
                    definition,
                    node,
                    fact_prefix=fact_prefix,
                    confirmed_set=confirmed_set,
                    value_fn=value,
                )
                initial_text = body_text
                source_fact_ids = body_fact_ids
            if resolution and resolution.render_action == "retain_not_applicable":
                initial_text = f"不适用。{resolution.rationale}"
                source_fact_ids = list(resolution.source_fact_ids)
            elif resolution and resolution.render_action == "retain_placeholder":
                initial_text = ""
                source_fact_ids = list(resolution.source_fact_ids)
            applicability_status = (
                resolution.status if resolution else "applicable"
            )
            applicability_render_action = (
                resolution.render_action if resolution else "retain_full"
            )
            drafting_readiness = _section_drafting_readiness(
                node,
                initial_text=initial_text,
                initial_data=initial_data,
                confirmed_set=confirmed_set,
                has_selected_children=node.node_id in selected_parent_node_ids,
                applicability_status=applicability_status,
                applicability_render_action=applicability_render_action,
            )
            seeds.append(
                MedicalWritingGreenfieldSectionSeed(
                    section_key=node.node_id,
                    heading=heading,
                    parent_key=node.parent_node_id,
                    ich_m11_anchor=(
                        "；".join(
                            f"ICH M11 {item}" for item in node.m11_coverage_anchors
                        )
                        if node.m11_coverage_anchors
                        else ""
                    ),
                    initial_text=initial_text,
                    source_fact_ids=source_fact_ids,
                    template_node_id=node.node_id,
                    section_number=section_numbers.get(node.node_id, ""),
                    node_kind=node.node_kind,
                    applicability_mode=node.applicability_mode,
                    applicability_status=applicability_status,
                    applicability_render_action=applicability_render_action,
                    applicability_rationale=(
                        resolution.rationale if resolution else ""
                    ),
                    repeatable=node.repeatable,
                    title_locked=node.title_locked,
                    interaction_types=node.interaction_types,
                    initial_data=initial_data,
                    **drafting_readiness,
                )
            )
        return seeds

    def module_resolutions(
        self,
        definition: Any,
        template: MedicalWritingProtocolTemplateDefinition | None = None,
    ) -> list[MedicalWritingProtocolModuleResolution]:
        template = template or self.definition()
        # Consume one confirmed current plan revision for module applicability.
        # Same fail-closed gate as section_seeds.
        design_projection = self._require_design_projection(
            definition, "sections_toc"
        )
        if template.template_id == TEMPLATE_ID:
            return _company_module_resolutions(
                template, definition, design_projection
            )
        # M11 templates: nodes without applicability_rules are always
        # applicable. Nodes with rules (e.g. interim analysis) go through
        # the same deterministic feature-gated resolution so they can be
        # omitted when the design declares the feature as not applicable.
        # Unlike the company template, M11 nodes with unknown status are
        # retained (backward-compatible replay) rather than omitted.
        facets = _project_facets(definition, design_projection)
        results: list[MedicalWritingProtocolModuleResolution] = []
        for node in template.nodes:
            if not node.applicability_rules:
                results.append(
                    MedicalWritingProtocolModuleResolution(
                        template_node_id=node.node_id,
                        semantic_node_id=node.semantic_node_id or node.node_id,
                        status="applicable",
                        render_action="retain_full",
                        resolution_source="template_required",
                        rationale="显式选择的历史模板按原章节树重放。",
                        affected_artifacts=_module_affected_artifacts(node),
                    )
                )
            else:
                resolution = _engine_module_resolution(definition, node, facets)
                if resolution.status == "unknown":
                    resolution = resolution.model_copy(
                        update={
                            "render_action": "retain_full",
                            "rationale": (
                                "研究设计未明确该模块的适用性，按模板默认保留。"
                            ),
                        }
                    )
                results.append(resolution)
        return results

    def blank_section_seeds(
        self,
        template: MedicalWritingProtocolTemplateDefinition | None = None,
    ) -> list[MedicalWritingGreenfieldSectionSeed]:
        """Materialize the canonical structure without inventing project facts."""
        template = template or self.definition()
        nodes = list(template.nodes)
        if template.template_id == TEMPLATE_ID:
            nodes = [node for node in nodes if not node.applicability_rules]
        section_numbers = (
            _continuous_section_numbers(nodes)
            if template.template_id == TEMPLATE_ID
            else {node.node_id: node.section_number for node in nodes}
        )
        selected_parent_node_ids = {
            node.parent_node_id for node in nodes if node.parent_node_id
        }
        return [
            MedicalWritingGreenfieldSectionSeed(
                section_key=node.node_id,
                heading=materialize_repeatable_objective_heading(
                    node.title_zh,
                    template_node_id=node.node_id,
                ),
                parent_key=node.parent_node_id,
                ich_m11_anchor=(
                    "；".join(f"ICH M11 {item}" for item in node.m11_coverage_anchors)
                    if node.m11_coverage_anchors
                    else ""
                ),
                initial_text="",
                source_fact_ids=[],
                template_node_id=node.node_id,
                section_number=section_numbers.get(node.node_id, ""),
                node_kind=node.node_kind,
                applicability_mode=node.applicability_mode,
                applicability_status="applicable",
                applicability_render_action="retain_full",
                applicability_rationale="空白模板仅生成稳定核心章节。",
                repeatable=node.repeatable,
                title_locked=node.title_locked,
                interaction_types=node.interaction_types,
                **_section_drafting_readiness(
                    node,
                    initial_text="",
                    initial_data={},
                    confirmed_set=set(),
                    has_selected_children=(
                        node.node_id in selected_parent_node_ids
                    ),
                    applicability_status="applicable",
                    applicability_render_action="retain_full",
                ),
            )
            for node in nodes
        ]
