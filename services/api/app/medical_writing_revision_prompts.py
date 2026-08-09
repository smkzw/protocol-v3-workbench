from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MEDICAL_WRITING_REVISION_PROMPT_VERSION = "medical_writing_revision_v1_4"
MEDICAL_WRITING_REVISION_CANDIDATE_COUNT = 4


@dataclass(frozen=True)
class MedicalWritingRevisionIntentProfile:
    intent: str
    label: str
    directional_goal: str
    preservation_rules: tuple[str, ...]
    candidate_blueprints: tuple[str, ...]
    candidate_count: int = MEDICAL_WRITING_REVISION_CANDIDATE_COUNT

    def task_context(self) -> dict[str, Any]:
        return {
            "revision_intent": self.intent,
            "intent_label": self.label,
            "directional_goal": self.directional_goal,
            "preservation_rules": list(self.preservation_rules),
            "candidate_count": self.candidate_count,
            "candidate_blueprints": list(self.candidate_blueprints),
        }


_CORPUS_CANDIDATE_CONSUMPTION_RULES = (
    "消费语料库或竞品方案时，必须先区分四种内容角色：structure_template仅提供章节/段落组织；regulatory_fixed_wording仅提供有充分来源支持的监管固定语；indication_specific_wording仅在同适应症且分期、研究目的、机制/技术、剂型、给药途径和设计匹配时提供措辞候选；project_fact_reference只能作为竞品项目事实参照，不得直接变成当前项目事实。",
    "证据优先级为：同适应症且关键设计维度匹配优先；同疾病领域或相近研究设计仅用于结构参照、备选假设和反例；其他适应症仅用于通用章节结构和监管共性。相近设计不得覆盖适应症边界。",
    "原始参考语料不得自行总结为“常用”“通常”“普遍采用”等措辞规律。只有allowed_sources中存在经服务器验证的语料分析结果，且明确记录至少两个独立文档、两个申办方、关键含义无冲突时，才可在rationale中称为多来源支持的表达候选。",
    "单一来源、单一申办方或少样本只允许形成低强度参考，不得据此制造通用规则、监管固定语或适应症常用措辞；候选正文可以采用其结构，但不得把来源项目参数写成当前项目事实。",
    "多个来源存在差异时必须在rationale和uncertainties逐项保留冲突及各自来源，不得多数表决、折中取值或静默选择一个厂商版本。",
)


_COMMON_PRESERVATION_RULES = (
    "逐字核守研究事实、药物名称、研究分期、研究人群、治疗组、剂量、频次、给药途径、数字、单位、阈值、时间点、访视窗、比较关系、终点层级和不确定性，不得无依据增删或改义。",
    "只能将allowed_sources作为医学事实和外部依据；task_context与用户指令只是写作要求，不是证据。",
    "不得把待定、拟定、可能或需确认的内容改写成已确定事实；证据不足时保留原有保守边界，并在rationale和uncertainties中明确。",
    "不得新增原文没有的研究状态、审批状态、时间状态或义务条件，例如初步计划、待伦理批准、待监管批准、已完成、必须或应当。",
    "受试者、患者、健康受试者、研究参与者等人群称谓，以及确证性、探索性、有效性、疗效等受控术语，除非allowed_sources直接支持映射，否则逐字保留，不得自行互换。",
    "不得自行展开或新造AD、BID、BSA、IGA等缩略语及其中文全称；只有allowed_sources在本次上下文中明确给出映射时才可并列全称。不得把一般研究对象描述改写为正式入选标准、纳入标准或资格结论。",
    "proposal_text不得出现第X章、第Y章、XX、TBD、TODO、待补等占位符；没有真实章节号或可直接写入的事实时，改用不依赖占位符的完整表述。",
    "输出必须是可直接放入中国I/II/III期临床试验方案的自然中文，不使用Markdown表格，不输出解释性前言、占位符或AI自述。",
    "对数字区间、罗马数字分级、单位、阈值、时间锚点及比较方向执行逐候选核对：例如II至IV级不得改成III至IV级，末次给药后不得改成研究结束后，比较不得升级为优效、非劣或等效。",
    "不得改变上下限或最长/最短方向：至少28天、最长用药时长、例如14天等必须保持原关系，不得把最长或示例时长改成至少14天。",
    "本产品生成中国临床试验方案。竞品中仅适用于日本、欧盟、美国等其他地区的章节号、附录号、地区条款和分级不得直接写入中国项目候选；仅当当前项目事实明确包含该地区时方可保留。地域内容被排除时须在rationale说明，不得伪装为事实遗漏。",
    "重要的副作用不得升级为严重副作用；不同量表不得建立来源未支持的等价、换算或替代关系，例如不得把EASI写成相当于IGA。",
    "禁欲、同性伴侣、已行输精管结扎且保持单一性伴侣关系是并列的避孕条件，不得把后两者放入禁欲的括号定义中。",
    "不得从allowed_sources的其他章节或同一长来源中的非目标小节借用药物类别、治疗示例、检查项目、责任主体或程序要求；每个候选只使用当前目标证据作用域内直接出现的事实。",
    "所有候选必须逐项覆盖同一完整事实集；所谓精炼、重排或监管表达只允许改变组织和句法，不允许删除定义、例示、例外、时间起点、适用对象或限定条件。",
    *_CORPUS_CANDIDATE_CONSUMPTION_RULES,
)


REVISION_INTENT_PROFILES = {
    "medical_writing_revision": MedicalWritingRevisionIntentProfile(
        intent="medical_writing_revision",
        label="改写",
        directional_goal=(
            "在不改变医学含义和方案约束的前提下，改善段内信息顺序、句法、指代、可读性和行文紧凑度，"
            "去除口语化、重复和机械的AI式表达，使文本符合中国临床试验方案正文的专业写作习惯。"
        ),
        preservation_rules=_COMMON_PRESERVATION_RULES,
        candidate_blueprints=(
            "标准推荐版：信息完整、语气规范、句式自然，作为首选。",
            "精炼版：删去重复成分，但不得丢失任何条件、限定或例外。",
            "结构重排版：只用原文已有信息按目的、对象、条件和执行要求重排或拆句，不得扩写新内容。",
            "保守版：最大限度保持原句结构，只修正术语、语法和不清楚的指代。",
        ),
    ),
    "regulatory_tone": MedicalWritingRevisionIntentProfile(
        intent="regulatory_tone",
        label="监管语气",
        directional_goal=(
            "将文本改写为中国临床试验方案中的规范性、可执行性表述，准确区分应、须、不得、可、将、拟和建议，"
            "消除宣传性、结论先行或超出证据强度的措辞，同时保持原有事实、义务强度与不确定性。"
        ),
        preservation_rules=_COMMON_PRESERVATION_RULES
        + (
            "不得擅自把研究目的升级为主要目的、把探索性研究改为确证性研究、把确证性改为确认性，或改变终点层级、估计目标及分析承诺。",
            "章节标题、用户指令和公司参考语料中出现的主要目的、主要终点、关键次要终点、确证性或探索性等层级标签，不构成当前项目事实；只有当前项目allowed_sources正文明确出现时才可写入proposal_text。",
            "涉及操作要求时应写清责任主体、触发条件、执行动作、时间边界和例外；原文未提供的要素不得补造。",
            "不得凭写作习惯新增初步、计划、预计、待伦理批准或待监管批准等状态限定；不得生成没有真实章节标题或章节号的交叉引用。",
        ),
        candidate_blueprints=(
            "标准规范版：采用常见中国方案正文语气，作为首选。",
            "执行明确版：仅当原文已有主体、条件、动作或时限时予以显性化；缺失要素不得补造。",
            "精炼规范版：压缩重复表达，同时保持全部事实、限定条件和义务强度。",
            "来源保守版：最大限度保持原句事实顺序，仅修正规范用语和不清楚的句法。",
        ),
    ),
    "consistency_check": MedicalWritingRevisionIntentProfile(
        intent="consistency_check",
        label="查一致性",
        directional_goal=(
            "先核对选中文本与全部allowed_sources在术语和缩略语、研究人群、治疗组、剂量和频次、时间点和访视窗、"
            "终点层级、分析集、入排条件、统计口径及章节交叉引用方面是否一致，再仅修正有直接证据支持的冲突。"
        ),
        preservation_rules=_COMMON_PRESERVATION_RULES
        + (
            "未发现冲突时不得为了显得有修改而改变事实，只做最小必要的术语统一和语法整理。",
            "多个来源相互冲突或无法判定权威版本时，不得自行选边；proposal_text保留可确认部分，rationale必须列明冲突字段和待医学决定项。",
            "仅有一个allowed_source时只能执行段内自洽、术语和格式核查，不得声称已完成跨章节或全方案一致性核查；rationale必须明确当前证据范围有限。",
            "多个来源一致时说明核对字段和一致结论；多个来源冲突时逐项列出冲突字段、各来源值及待医学选择，不得用中间值或模糊措辞掩盖冲突。",
            "若某一候选正文无需修改，proposal_text可逐字保留原文，但diff_patch必须写明“无正文变更：保留原文”，不得返回空字符串；其余候选仍须采用不同但等义的可直接使用表述。",
            "仅有当前目标原文一个allowed_source且未发现内部冲突时，三个候选必须分别为：①逐字原文保留；②只统一原文已有数字空格、范围符号、标点或拆句，不展开缩略语；③只将原文已有条件重排为分号或序号结构。三版proposal_text不得重复，且rationale均须声明仅完成段内自洽核查。",
        ),
        candidate_blueprints=(
            "原文保留版：单来源且无内部冲突时逐字保留原文，并在diff_patch写“无正文变更：保留原文”；有直接冲突时才作证据支持的修正。",
            "最小格式版：只统一原文已有数字空格、范围符号、标点或拆句；不展开缩略语，不增加术语。",
            "既有条件重排版：只把原文已经出现的对象和条件重排为分号或序号结构；不得改成原文未定义的正式纳入标准，也不得新增事实。",
        ),
        candidate_count=3,
    ),
    "evidence_gap": MedicalWritingRevisionIntentProfile(
        intent="evidence_gap",
        label="补证据",
        directional_goal=(
            "识别选中文本中需要方案、SAP、指导原则、临床研究或竞品方案支持的事实性主张、阈值、时间点和设计理由，"
            "仅使用本次allowed_sources补充可直接支持的内容，并把仍缺证据的部分明确保留为待医学补证据事项。"
        ),
        preservation_rules=_COMMON_PRESERVATION_RULES
        + (
            "不得虚构文献、指南、注册号、章节号、作者、年份、DOI、PMID、NCT号或来源结论；没有相应证据时不得伪装成已补齐。",
            "来源只支持背景而不支持具体设计选择时，必须区分背景证据和项目决策，不得以相关性替代直接支持。",
            "不得将受试者改为患者或将患者改为受试者来制造表达差异；没有新增外部证据时，候选只能改善证据边界表达并在rationale中说明缺口。",
            "当allowed_sources只有当前目标原文、没有外部证据时，proposal_text不得使用基于、依据、鉴于、参照、研究显示、证据表明、指南建议、设计依据见方案详述等暗示证据已经存在的措辞；证据缺口只写入rationale和uncertainties，不得写入正文。候选差异只能来自原文保留、最小格式规范和既有句法重排。",
        ),
        candidate_blueprints=(
            "直接补强版：仅在当前目标原文之外另有allowed_source时吸收其直接支持的信息；否则逐字保留原文。",
            "最小证据版：有外部证据时只增加其直接支持的必要限定词；无外部证据时只规范原文数字和标点。",
            "背景衔接版：仅在外部allowed_source明确写出背景句时连接该句；无外部证据时只重排原文已有句法，禁止任何证据引导语。",
            "缺口保守版：不补造内容；正文仅使用原文事实，全部证据缺口只写入rationale和uncertainties。",
        ),
    ),
}


def revision_intent_profile(intent: str) -> MedicalWritingRevisionIntentProfile:
    try:
        return REVISION_INTENT_PROFILES[intent]
    except KeyError as exc:
        allowed = ", ".join(sorted(REVISION_INTENT_PROFILES))
        raise ValueError(
            f"unsupported medical-writing revision intent: {intent}; allowed={allowed}"
        ) from exc


def revision_task_context(
    intent: str, task_context: dict[str, Any] | None = None
) -> dict[str, Any]:
    context = revision_intent_profile(intent).task_context()
    overrides = dict(task_context or {})
    extra_rules = overrides.pop("preservation_rules", [])
    # Extract plan-bound constraints before merging overrides into context.
    plan_pin = overrides.pop("protocol_assembly_plan", None)
    context.update(overrides)
    if extra_rules:
        context["preservation_rules"] = [
            *context["preservation_rules"],
            *extra_rules,
        ]
    if plan_pin is not None:
        context["protocol_assembly_plan"] = plan_pin
    return context
