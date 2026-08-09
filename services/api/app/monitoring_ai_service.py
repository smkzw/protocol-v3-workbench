from __future__ import annotations

import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    ValidationError,
    model_validator,
)

from .ai_gateway import (
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiProvider,
    AiProviderRuntimeError,
    AiTaskType,
    DisabledAiProvider,
    ai_gateway_status_from_env,
    configured_ai_provider_from_env,
)
from .ai_role_runtime_settings import (
    INDEPENDENT_AI_ROLE,
    runtime_ai_role_settings_store,
)
from .monitoring_ai_contracts import (
    MONITORING_AI_SCHEMA_VERSION,
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobCreate,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
    validate_candidates_for_job,
)
from .monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiStateConflictError,
)
from .monitoring_deterministic_metadata_mapping import (
    DETERMINISTIC_METADATA_MAPPING_VERSION,
    DETERMINISTIC_METADATA_MODEL,
    DETERMINISTIC_METADATA_PROFILE_ID,
    DETERMINISTIC_METADATA_PROVENANCE_SCHEMA_VERSION,
    DETERMINISTIC_METADATA_PROVIDER,
    LEGACY_V7_DETERMINISTIC_REPAIR_REASON,
    LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
    deterministic_metadata_decision,
    deterministic_metadata_mappings,
    deterministic_metadata_provenance,
    partition_metadata_fields,
)
from .monitoring_mapping_contract import (
    MonitoringFieldKind,
    validate_monitoring_mapping_semantics,
)
from .monitoring_mapping_semantic_quality import (
    ROLE_CATALOG_VERSION,
    RULE_CATALOG_VERSION,
)
from .monitoring_ai_field_profiler import FIELD_RELATIONSHIP_TYPES
from .monitoring_ai_source_packet import (
    MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS,
    PROTOCOL_EVIDENCE_PACKET_VERSION,
    PROTOCOL_STRUCTURAL_REPAIR_VERSION,
    ProtocolStructuralRepairError,
    focus_protocol_provider_evidence,
    repair_protocol_structural_bundles,
)
from .monitoring_capability_guard import (
    require_monitoring_capability_snapshot,
    required_capabilities_for_rule,
)
from .monitoring_protocol_rules import ProtocolFact
from .monitoring_rule_templates import (
    TEMPLATE_PAYLOAD_KEY,
    compile_monitoring_rule_template,
)


PROMPT_VERSION_BY_TASK: Dict[MonitoringAiTaskType, str] = {
    MonitoringAiTaskType.LISTING_FIELD_MAPPING: ("monitoring-listing-field-mapping-v16"),
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING: (
        "monitoring-protocol-clause-structuring-v12"
    ),
    MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION: (
        "monitoring-rule-template-recommendation-v1"
    ),
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS: (
        "monitoring-cross-table-clue-synthesis-v3"
    ),
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY: ("monitoring-risk-evidence-summary-v2"),
    MonitoringAiTaskType.RISK_QUESTION_ANSWER: ("monitoring-risk-question-answer-v2"),
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES: (
        "monitoring-query-explanation-candidates-v2"
    ),
}

AI_TASK_TYPE_BY_MONITORING_TASK: Dict[MonitoringAiTaskType, AiTaskType] = {
    MonitoringAiTaskType.LISTING_FIELD_MAPPING: (AiTaskType.LISTING_SEMANTIC_MAPPING),
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING: (
        AiTaskType.PROTOCOL_RULE_EXTRACTION
    ),
    MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION: (
        AiTaskType.PROTOCOL_RULE_EXTRACTION
    ),
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS: (
        AiTaskType.MONITORING_RISK_INTERPRETATION
    ),
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY: (
        AiTaskType.MONITORING_RISK_INTERPRETATION
    ),
    MonitoringAiTaskType.RISK_QUESTION_ANSWER: (
        AiTaskType.MONITORING_RISK_INTERPRETATION
    ),
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES: (
        AiTaskType.ANALYSIS_RESULT_EXPLANATION
    ),
}

TASK_CONTRACTS: Dict[MonitoringAiTaskType, str] = {
    MonitoringAiTaskType.LISTING_FIELD_MAPPING: (
        "基于完整冻结批次的字段画像提出字段语义、域、角色和关联字段候选。"
        "不得只查看或概括前五行，不得把样例值当作完整数据，也不得据此生成风险结论。"
    ),
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING: (
        "把方案原文条款拆解为可追溯的适用对象、条件、时间窗、阈值、例外和动作候选。"
        "必须使用证据包提供的同章节邻接、表格表头与同行、列表标题与连续条目。"
        "不得把措施单元格脱离同行阈值，不得补写原文没有的医学要求。"
        "必须区分“方案未规定”和“当前证据包未检索到”：没有全篇核验授权时，"
        "后者只能标为检索缺口。原文对同一动作存在强制、可选或禁止冲突时，"
        "必须并列保留并要求用户裁决，禁止静默选择。估计目标中的目标人群"
        "不得直接生成入排规则。CM仅表示非试验用药或治疗，试验药物给药、"
        "剂量调整、暂停、停药、重启和依从性必须保持独立。"
    ),
    MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION: (
        "仅根据用户已确认的方案事实草稿、当前激活的不可变字段映射和能力快照，"
        "提出1至3个可由现有确定性规则编译器执行的模板建议。不得补造方案事实、"
        "不得使用未冻结字段语义，不得把CM与试验药物给药或变更混为一类。"
    ),
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS: (
        "跨表连接同一受试者、访视、事件和用药的线索，提出2至3个值得人工复核、"
        "彼此不重复的解释候选。每个候选必须引用至少两个真实原始数据域，"
        "不得用分析主题、派生概念或方案条款冒充第二个数据域；"
        "不得把时间相关性直接表述为因果关系或确定性风险结论。"
    ),
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY: (
        "将既有风险对象的方案依据、原始数据和系统规则整理为简洁、直观、可追溯的证据摘要。"
        "必须区分事实、推断、建议和数据缺口，不得改变风险级别或处置状态。"
    ),
    MonitoringAiTaskType.RISK_QUESTION_ANSWER: (
        "围绕用户问题，仅根据本次授权证据回答，并明确证据不足、冲突和需要人工判断之处。"
        "不得把回答写成医学批准、最终Query或正式关闭结论。"
    ),
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES: (
        "生成2至3个可供医学经理选择和精调的Query或解释文本候选。"
        "候选需准确说明观察事实、需澄清问题及期望补充内容，彼此应有实质差异；"
        "不得声称已医学批准或可直接外发。"
    ),
}

FIELD_MAPPING_SCIENTIFIC_BOUNDARY: Dict[str, Any] = {
    "source_record": (
        "records/active_slices/medical_monitoring_goal_p4_20260729/"
        "FIELD_MAPPING_SCIENTIFIC_BOUNDARY.md"
    ),
    "input_layer": (
        "输入是EDC导出的data listing；不得声称输入文件是SDTM或字段已符合SDTM。"
    ),
    "standards_layer": (
        "CDASH、SDTM或受控术语只能作为standards_reference可选参照，"
        "不能替代项目来源语义和人工映射确认；StudyOID、MetaDataVersionOID、"
        "StudyEventOID、FormOID、ItemGroupOID等EDC技术元数据优先参照ODM，"
        "不得把OID值直接翻译为访视名称。"
    ),
    "field_layers": (
        "每个来源字段必须标记为source_collected、source_metadata、"
        "standardized_coded、deterministic_derived或unmapped；"
        "standardized_coded必须给出编码词典/版本/来源字段血缘，"
        "deterministic_derived必须给出确定性计算血缘。"
    ),
    "domain_independence": "同名字段跨域独立判断，不得跨域合并语义。",
    "cm_ip_boundary": (
        "CM仅表示非试验用药/治疗；试验药物给药、剂量调整、停药、重启和"
        "依从性必须使用独立IP角色，不得归入CM。"
    ),
    "evidence_boundary": (
        "每项映射必须引用完整字段画像中的域、字段、频次、类型、代表值或"
        "异常证据；术语与编码一致性必须依据同一行配对指标，不得仅凭字段名"
        "或边际唯一值数猜测。"
    ),
    "uncertainty_boundary": ("不确定性必须说明缺少什么信息，以及用户需要确认什么。"),
}
DEFAULT_FIELD_MAPPING_CHUNK_SIZE = 12
DEFAULT_MONITORING_AI_TIMEOUT_SECONDS = 600.0
MONITORING_PRODUCT_AI_TRANSPORT = "openai_compatible"
_READ_ONLY_CONTEXT_ROLES_WITH_VALUES = frozenset(
    {
        "form_name",
        "form_name_duplicate",
        "page_name",
        "study_name",
    }
)
_MAX_CONTEXT_VALUES = 5
_MAX_CONTEXT_VALUE_LENGTH = 240
_SCALE_CONTEXT_MARKERS = (
    "量表",
    "问卷",
    "评估",
    "评分",
    "scale",
    "questionnaire",
    "assessment",
    "score",
)
_NON_IP_OBJECT_IDENTITIES = frozenset(
    {
        "background_therapy",
        "rescue_therapy",
        "concomitant_non_ip",
        "other_non_ip_treatment",
    }
)
_NON_IP_CONTEXT_MARKERS = {
    "background_therapy": (
        "背景治疗",
        "基础治疗",
        "既往治疗",
        "既往用药",
        "background therapy",
        "background treatment",
        "prior therapy",
        "prior treatment",
        "prior medication",
        "prior medications",
    ),
    "rescue_therapy": (
        "救援治疗",
        "补救治疗",
        "rescue therapy",
        "rescue treatment",
        "rescue medication",
    ),
    "concomitant_non_ip": (
        "合并用药",
        "合并治疗",
        "伴随用药",
        "伴随治疗",
        "非研究用药",
        "非试验用药",
        "非研究治疗",
        "concomitant medication",
        "concomitant treatment",
        "concomitant therapy",
        "non-study medication",
        "non-study treatment",
        "non-study therapy",
    ),
}
_IP_CONTEXT_MARKERS = (
    "试验药物",
    "研究药物",
    "随机治疗",
    "随机分组",
    "investigational product",
    "study drug",
    "randomized treatment",
    "randomised treatment",
    "imp administration",
)

TASK_CANDIDATE_TYPES: Dict[MonitoringAiTaskType, Tuple[str, ...]] = {
    MonitoringAiTaskType.LISTING_FIELD_MAPPING: ("listing_field_mapping_set",),
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING: ("protocol_clause_structure",),
    MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION: (
        "deterministic_rule_template",
    ),
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS: ("cross_table_clue",),
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY: ("risk_evidence_summary",),
    MonitoringAiTaskType.RISK_QUESTION_ANSWER: ("risk_question_answer",),
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES: (
        "query_candidate",
        "explanation_candidate",
    ),
}

_FORBIDDEN_DEFINITIVE_PHRASES = (
    "已医学批准",
    "已获医学批准",
    "待医学批准",
    "待批准",
    "无需人工复核",
    "可直接外发",
    "确定为AE漏报",
    "确定为MH漏报",
    "确定为方案违背",
)
_UNAUTHORIZED_PROTOCOL_ABSENCE_RE = re.compile(
    r"(?:方案|研究方案|本方案).{0,12}(?:未规定|未提供|未说明|缺少|不存在)",
    re.IGNORECASE,
)
_NEGATED_PROTOCOL_ABSENCE_PREFIX_RE = re.compile(
    r"(?:"
    r"不能|不得|不可|无法|不应|不宜|不代表|并不代表|"
    r"不能据此|不得据此|不可据此|无法据此"
    r").{0,12}(?:断言|认定|认为|推断|说明|表示)?$",
    re.IGNORECASE,
)
_DIRECT_IP_CHANGE_RE = re.compile(
    r"(?:"
    r"(?:停用|停药|暂停|中断|停止给药|重新给药|恢复给药|重启|"
    r"剂量调整|调整剂量|减量).{0,6}(?:研究药物|试验药物|研究治疗)"
    r"|(?:研究药物|试验药物|研究治疗).{0,8}(?:停用|停药|暂停|"
    r"中断|停止给药|重新给药|恢复给药|重启|剂量调整|调整剂量|减量)"
    r")"
)
_DIRECT_CM_CHANGE_RE = re.compile(
    r"(?:"
    r"(?:停用|暂停|调整|新增|开始|停止).{0,6}"
    r"(?:合并用药|伴随用药|非试验用药|合并治疗)"
    r"|(?:合并用药|伴随用药|非试验用药|合并治疗).{0,8}"
    r"(?:停用|暂停|调整|新增|开始|停止)"
    r")"
)
_VISIT_MEDICATION_TIMING_EXCLUSION = (
    r"(?!\s*(?:(?:的)?(?:之前|之后|前|后)|当天|当日|期间|"
    r"之内|以内|时|日|\d+\s*[天日周月](?:内|以内|之前|之后|前|后)?))"
)

_VISIT_TOPIC_MEDICATION_ACTION_RE = re.compile(
    r"(?:"
    # stop/pause/restart/dose-change with a bounded IP/CM object, both orders
    r"(?:停用|停药|暂停|中断|停止给药|重新给药|恢复给药|重启|"
    r"剂量调整|调整剂量|减量|增加剂量).{0,8}"
    r"(?:研究药物|试验药物|研究治疗|试验用药|合并用药|伴随用药|"
    r"非试验用药|合并治疗)"
    r"|(?:研究药物|试验药物|研究治疗|试验用药|合并用药|伴随用药|"
    r"非试验用药|合并治疗).{0,8}"
    r"(?:停用|停药|暂停|中断|停止给药|重新给药|恢复给药|重启|"
    r"剂量调整|调整剂量|减量|增加剂量)"
    # first/initial dose and plain administration directives, standalone
    r"|(?:首次|第一次|第1次)(?:给药|用药|应用|使用)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    + r"|(?:第1天|第一天|开始|完成|继续|结束|恢复)(?:给药|用药|应用)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    + r"|(?:给药|用药)治疗"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    + r"|(?:服用|服药)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    # first/initial dose with a bounded object (action-object order)
    + r"|(?:首次|第一次|第1次)(?:应用|使用|给药|用药)"
    r"(?:研究药物|试验药物|试验用药|合并用药|伴随用药)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    # administration verbs with bounded intervening words (action-object order)
    + r"|(?:给予|接受|使用|服用|口服|应用|注射|输注|开始|新增|加用|"
    r"完成|继续|结束)[^。；\n]{0,8}?"
    r"(?:研究药物|试验药物|研究治疗|试验用药|合并用药|伴随用药)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    # object-prefixed administration (object-action order)
    + r"|(?:研究药物|试验药物|研究治疗|试验用药|合并用药|伴随用药|"
    r"非试验用药|合并治疗)[^。；\n]{0,8}?"
    r"(?:给药|用药|使用|应用|治疗)"
    + _VISIT_MEDICATION_TIMING_EXCLUSION
    + r")"
)
_VISIT_TOPIC_WITHDRAWAL_RE = re.compile(
    r"(?:提前退出|退出(?:本|该)?研究(?!中心)|退出试验|退出知情同意|"
    r"(?:终止|中止)(?:参与)?(?:本|该)?研究(?!药物)|"
    r"停止参加(?:本|该)?研究(?!中心|药物)|"
    r"研究中心无法(?:联系受试者|与受试者取得联系)|"
    r"(?:撤回|撤销)其?(?:知情)?同意|撤回知情|失访|脱落)"
)
_VISIT_TOPIC_COLLECTION_RE = re.compile(
    r"(?:不良事件收集|AE收集|不良事件记录|AE记录|不良事件采集|"
    r"合并用药收集|合并用药记录|合并用药采集|"
    r"伴随用药收集|伴随用药记录|伴随用药采集|"
    r"CM收集|CM记录|"
    r"(?:记录|收集|采集|询问).{0,20}?"
    r"(?:不良事件|伴随用药|合并用药|AE(?![A-Za-z0-9])|CM(?![A-Za-z0-9]))|"
    r"(?:不良事件|伴随用药|合并用药|AE(?![A-Za-z0-9])|CM(?![A-Za-z0-9]))"
    r".{0,16}?(?:记录|收集|采集)|"
    r"(?<![A-Za-z0-9])(?:AE|CM)(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
_VISIT_SCHEDULE_FAMILY_RE = re.compile(
    r"(?:时间窗|访视窗|访视窗口|研究日|允许范围|"
    r"(?<!计划外)(?<!计划外的)(?<!非计划)(?<!非计划的)(?<!额外)(?<!额外的)访视计划|"
    r"(?<!计划外)(?<!计划外的)(?<!非计划)(?<!非计划的)(?<!额外)(?<!额外的)访视安排|"
    r"(?<!计划外)(?<!计划外的)(?<!非计划)(?<!非计划的)(?<!额外)(?<!额外的)访视顺序|"
    r"(?<!计划外)(?<!计划外的)(?<!非计划)(?<!非计划的)(?<!额外)(?<!额外的)"
    r"(?<!调整)(?<!更改)(?<!修改)访视日期|"
    r"(?<!计划外)(?<!计划外的)(?<!非计划)(?<!非计划的)(?<!额外)(?<!额外的)访视时间|"
    r"(?<!非)计划访视|末次(?:计划)?访视|访视先后(?:顺序|次序)|访视次序|"
    r"(?:研究|试验)(?:结束|终止)访视|"
    r"(?:第\s*\d+\s*周|第[一二三四五六]周|"
    r"D\s*\d+\s*[±]\s*\d+\s*d)访视)"
)
_VISIT_TOPIC_DISPENSING_PK_RE = re.compile(
    r"(?:发放|分发|回收|称重|依从性|药代动力学|血药浓度|PK)"
)
_VISIT_TOPIC_SAFETY_FOLLOWUP_RE = re.compile(
    r"(?:安全性随访|安全随访)"
)
_VISIT_TOPIC_STUDY_COMPLETION_RE = re.compile(
    r"(?:"
    # subject/study completion or end with 试验/研究 as the study object;
    # never 试验流程表/试验方案/试验流程图/试验期间
    r"(?:视为(?:该例|该|每例)?受试者|受试者|即视为|则视为)?"
    r"(?:完成|结束)(?:本|整个|全部)?(?:临床试验|临床研究|研究|试验)"
    r"(?!流程|方案|流程图|期间)"
    r"|(?:完成|结束)(?:本|整个|全部)?(?:临床试验|临床研究|研究|试验)"
    r"(?!流程|方案|流程图|期间)"
    # Explicit study end/termination determinations. A bare end term at a
    # sentence boundary, a 判定/定义 label, or a time/date definition is a
    # study-state fact. The same words followed by 访视 or used as a temporal
    # anchor (结束前/后/时, 结束时间前/后, 结束时点前/后) remain visit-schedule
    # context and are not matched here.
    r"|(?:视为|即视为|则视为)(?:整个|全部|本)?(?:试验|研究)(?:结束|终止)"
    r"(?!访视)"
    r"|(?:整个|全部|本)?(?:试验|研究)(?:结束|终止)"
    r"(?:时点|时间|日期)\s*(?:定义|判定)?\s*为"
    r"|(?:整个|全部|本)?(?:试验|研究)(?:结束|终止)(?:判定|定义)"
    r"|(?:整个|全部|本)?(?:试验|研究)(?:结束|终止)(?=$|[，。；\n])"
    # study start determination
    r"|(?:总体|整个|全部|本)?(?:试验|研究)(?:从|自|于)"
    r"[^，。；\n]{0,12}?(?:开始|起算)"
    r")"
)
_VISIT_TOPIC_DIAGNOSTIC_SCHEMA_VERSION = (
    "monitoring_visit_topic_boundary_diagnostics_v1"
)
_VISIT_TOPIC_REPAIR_ACTION = "regenerate_entire_user_visible_field"
_VISIT_TOPIC_FORBIDDEN_FAMILY_PATTERNS = (
    ("medication_action", _VISIT_TOPIC_MEDICATION_ACTION_RE),
    (
        "dispensing_return_weighing_adherence_pk",
        _VISIT_TOPIC_DISPENSING_PK_RE,
    ),
    ("early_or_consent_withdrawal", _VISIT_TOPIC_WITHDRAWAL_RE),
    ("safety_follow_up", _VISIT_TOPIC_SAFETY_FOLLOWUP_RE),
    ("ae_or_cm_collection", _VISIT_TOPIC_COLLECTION_RE),
    ("subject_or_study_completion", _VISIT_TOPIC_STUDY_COMPLETION_RE),
)
_VISIT_RESCHEDULE_FAMILY_RE = re.compile(
    r"(?:改期|重新安排|补访|漏访|补做|补查|重访|错过访视|未完成访视|"
    r"落访|延期|调整访视日期|更改访视日期|修改访视日期)"
)
_VISIT_UNSCHEDULED_FAMILY_RE = re.compile(
    r"(?:计划外(?:的)?访视|非计划(?:的)?访视|额外(?:的)?访视|"
    r"计划外(?:的)?随访|非计划(?:的)?随访|临时访视|加访)"
)
_VISIT_RESCHEDULE_OBJECT_RE = re.compile(
    r"(?:调整|更改|修改|重新安排)\s*"
    r"(?:时间窗|访视窗|访视窗口|研究日|允许范围|计划访视|访视计划|"
    r"访视安排|访视时间|访视顺序|(?:计划)?访视日期)|"
    r"(?:时间窗|访视窗|访视窗口|研究日|允许范围|计划访视|访视计划|"
    r"访视安排|访视时间|访视顺序|(?:计划)?访视日期|"
    r"(?:第\s*\d+\s*周|第[一二三四五六]周|D\s*\d+\s*[±]\s*\d+\s*d)访视)"
    r"\s*(?:(?:均|都)\s*)?"
    r"(?:(?:仍)?(?:应当|应|需要|需|必须|须|可以|可|将)\s*)?"
    r"(?:进行\s*)?(?:改期|延期|补访|调整|更改|修改|重新安排)"
)
_VISIT_RESCHEDULE_TARGET_RE = re.compile(
    r"(?:在|于|至).{0,6}?(?:时间窗|访视窗|访视窗口|研究日|允许范围|"
    r"计划访视|访视计划|访视安排|访视时间|访视顺序|(?:计划)?访视日期|"
    r"(?:第\s*\d+\s*周|第[一二三四五六]周|D\s*\d+\s*[±]\s*\d+\s*d)访视)|"
    r"(?:时间窗|访视窗|访视窗口|研究日|允许范围|"
    r"计划访视|访视计划|访视安排|访视时间|访视顺序|(?:计划)?访视日期|"
    r"(?:第\s*\d+\s*周|第[一二三四五六]周|D\s*\d+\s*[±]\s*\d+\s*d)访视)"
    r".{0,8}?(?:内|以内|之内|范围内)"
)
_VISIT_ACTION_FAMILY_HEAD_PATTERN = (
    r"(?:改期|延期|补访|重新安排|调整|更改|修改|"
    r"计划外(?:的)?访视|非计划(?:的)?访视|额外(?:的)?访视|"
    r"临时访视|加访)"
)
_VISIT_SCHEDULE_PREDICATE_RE = re.compile(
    r"(?:完成(?!\s*"
    + _VISIT_ACTION_FAMILY_HEAD_PATTERN
    + r")|参加|执行|随访|到访|记录|为|遵循|保持|遵守|进行(?!\s*"
    + _VISIT_ACTION_FAMILY_HEAD_PATTERN
    + r"))"
)
_VISIT_SCHEDULE_DEFINITION_RE = re.compile(
    r"(?:访视窗口|访视窗|时间窗)\s*(?:规定\s*)?为\s*"
    r"(?:(?:±|\+/-)\s*)?\d+(?:\.\d+)?\s*(?:小时|天|日|周|月)"
)
_VISIT_SCHEDULE_REFERENCE_COMPLEMENT_RE = re.compile(
    # Plain nonnumeric, non-ordering schedule terms used as a reschedule
    # reference complement (以 <时间窗/访视窗/访视日/…> 为/作为 <参照|依据|
    # 基准>, e.g. 以试验流程表规定的时间窗为原始参照). Numeric, week/day,
    # D-day and ordering reference forms are handled by
    # _VISIT_INDEPENDENT_SCHEDULE_REFERENCE_RE, which is checked first and
    # keeps those assertions independent schedule content.
    r"以\s*[^，。；\n]{0,16}?(?:时间窗|访视窗|访视窗口|研究日|允许范围|"
    r"访视计划|访视安排|访视日期|访视时间|访视日|计划访视)"
    r"\s*(?:为|作为)\s*(?:原始\s*|参考\s*)?(?:参照|依据|基准)"
)
_VISIT_INDEPENDENT_SCHEDULE_REFERENCE_RE = re.compile(
    # A reference complement whose phrase carries an independent numeric,
    # week/day, D-day or ordering assertion stays schedule even when the
    # candidate has a real reschedule action: 以第十二周的计划访视为参照,
    # 以D15的访视计划为参照, 以72小时的访视窗口为参照, 以3个工作日的访视
    # 窗口为参照, 以原定访视先后次序和访视安排为参照.
    r"以\s*[^，。；\n]{0,16}?"
    r"(?:第\s*(?:\d+|[零〇一二两三四五六七八九十百]+)\s*(?:周|天|日)|"
    r"研究第\s*(?:\d+|[零〇一二两三四五六七八九十百]+)\s*(?:天|日)|"
    r"D\s*\d+(?:\s*[±]\s*\d+)?|"
    r"(?:\d+|[±]|[零〇一二两三四五六七八九十百]+)\s*(?:个\s*)?"
    r"(?:小时|时|天|日|周|月|工作日)|"
    r"访视先后(?:顺序|次序)|访视顺序|访视次序)"
    r"[^，。；\n]{0,16}?"
    r"(?:时间窗|访视窗|访视窗口|研究日|允许范围|"
    r"访视计划|访视安排|访视日期|访视时间|访视日|计划访视|"
    r"访视先后(?:顺序|次序)|访视顺序|访视次序)"
    r"\s*(?:为|作为)\s*(?:原始\s*|参考\s*)?(?:参照|依据|基准)"
)
_VISIT_TRIGGER_CLAUSE_RE = re.compile(
    r"(?:若|如果|一旦|无法|未能|不能|难以)"
)
_VISIT_DATA_GAP_RETRIEVAL_FRAME_RE = re.compile(
    r"(?:"
    r"未检索到|未找到|未包含|未提供|未收录|未发现|未明确|未规定|未说明|"
    r"未列出|未展开|未获取到|"
    r"证据不足|证据不充分|证据有限|缺乏|缺失|缺少|"
    r"无法确认|无法判断|难以确认|难以判断|不确定|"
    r"待确认|待核实|待补充|待检索|待进一步检索|需进一步检索|"
    r"需进一步确认|需要进一步确认|需用户裁决|需要用户裁决|"
    r"是否|能否|有无|疑问|存疑|可能存在于"
    r")"
)
_VISIT_DATA_GAP_SCOPE_BOUNDARY_RE = re.compile(
    # Strong boundaries (。；！？ and newline) plus adversative connectors
    # (然而/但/同时) reset the retrieval scope. Coordination (且/并/而/、)
    # never resets it: a retrieval scope established before the first
    # family span propagates forward across coordination.
    r"[。；！？\n]|然而|但|同时"
)
# Per-candidate diagnostic ceiling. The aggregate builder dynamically budgets
# below this ceiling after reserving every full candidate marker/title and one
# complete locator inside the global controlled repair error.
_CANDIDATE_DIAGNOSTIC_LIMIT = 700
_CONTROLLED_VALIDATION_ERROR_LIMIT = 4_000
_VISIT_NORMATIVE_SCHEDULE_RE = re.compile(
    r"(?:应|必须|需|须)"
)
_VISIT_QUANTIFIED_SCHEDULE_RE = re.compile(
    r"(?:所有|全部|各(?:次)?)(?:计划)?访视.{0,8}?(?:均|都|一律)"
)
_VISIT_WEEKDAY_ORDERING_SCHEDULE_RE = re.compile(
    r"(?:第\s*\d+\s*周|第[一二三四五六]周|"
    r"D\s*\d+\s*[±]\s*\d+\s*d)访视|访视顺序"
)
_FORBIDDEN_SDTM_ASSERTIONS = (
    "该文件是SDTM",
    "该文件为SDTM",
    "字段已符合SDTM",
    "字段符合SDTM",
    "SDTM compliant",
)
_NON_SPECIFIC_CODING_SYSTEM_RE = re.compile(
    r"(?:unspecified|unknown|待确认|未指定|不明确|不详)",
    re.IGNORECASE,
)
_DICTIONARY_VERSION_FIELD_RE = re.compile(
    r"(?:^|[_-])(?:M?DRAVER|DRUGVER|WHODDVER|DICT(?:IONARY)?VER"
    r"|CODELISTVER|CODINGVER|VERSION|VER)(?:$|[_-])",
    re.IGNORECASE,
)
_UNCERTAIN_FORMULA_RE = re.compile(
    r"(?:待确认|可能|推测|假设|未知|未提供|不明确|不详|"
    r"to\s+be\s+confirmed|unknown|unspecified|may\s+be)",
    re.IGNORECASE,
)
_SERVICE_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _require_service_sha256(value: Any, field_name: str) -> str:
    """Require a canonical persisted digest without rewriting its identity."""

    if not isinstance(value, str) or not _SERVICE_SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def monitoring_field_profile_source_binding(
    profile_sha256: str,
) -> MonitoringAiSourceBinding:
    cleaned = _require_service_sha256(profile_sha256, "profile_sha256")
    return MonitoringAiSourceBinding(
        source_entry_id=f"field-profile:{cleaned[:32]}",
        source_content_sha256=cleaned,
    )


def monitoring_revision_with_field_profile(
    revision: MonitoringAiInputRevision,
    profile_sha256: str,
) -> MonitoringAiInputRevision:
    profile_source = monitoring_field_profile_source_binding(profile_sha256)
    sources = tuple(
        source
        for source in revision.sources
        if not source.source_entry_id.startswith("field-profile:")
    )
    return MonitoringAiInputRevision.model_validate(
        {
            **revision.model_dump(mode="json"),
            "sources": [
                *[source.model_dump(mode="json") for source in sources],
                profile_source.model_dump(mode="json"),
            ],
        }
    )


def _contains_forbidden_sdtm_assertion(value: str) -> bool:
    clauses = re.split(
        r"[，。；;.!！？?]|\b(?:but|however|yet)\b|(?:但是|但|然而)",
        value,
        flags=re.IGNORECASE,
    )
    markers = tuple(
        re.sub(r"\s+", "", marker).casefold()
        for marker in (
            *_FORBIDDEN_SDTM_ASSERTIONS,
            "是SDTM",
            "为SDTM",
            "符合SDTM",
            "SDTM compliant",
        )
    )
    qualifier_patterns = (
        r"(?:不|非|未|无|勿|莫|否|尚未|不能|不得|不可|不应|无法)"
        r"[^，。；;.!！？?]{0,18}$",
        r"(?:不能据此|不代表|不等于|不意味着|不可据此|不得据此|"
        r"不应据此|是否|尚需|仍需|有待|需要|需由)[^，。；;.!！？?]{0,24}$",
        r"(?:not|cannot|can't|must not|should not|does not|do not|"
        r"whether|requires?confirmation|pendingconfirmation)"
        r"[^,.;!?]{0,32}$",
    )
    for clause in clauses:
        compact = re.sub(r"\s+", "", clause).casefold()
        for marker in markers:
            start = compact.find(marker)
            while start >= 0:
                prefix = compact[:start]
                if not any(
                    re.search(pattern, prefix, flags=re.IGNORECASE)
                    for pattern in qualifier_patterns
                ):
                    return True
                start = compact.find(marker, start + len(marker))
    return False


def _field_mapping_assertion_text(
    structured_payload: Dict[str, Any],
) -> str:
    mappings = []
    for item in structured_payload.get("field_mappings", []):
        mapping = dict(item)
        reference = mapping.get("standards_reference")
        if isinstance(reference, dict):
            mapping["standards_reference"] = {
                "reference_only": reference.get("reference_only"),
                "uncertainty": reference.get("uncertainty", ""),
            }
        mappings.append(mapping)
    return canonical_json({"field_mappings": mappings})


def _contains_internal_monitoring_identifier(value: str) -> bool:
    return bool(
        re.search(
            r"(?<![A-Za-z0-9])(?:riskinst|monai|monrisk|monsrc)_"
            r"[A-Za-z0-9_-]+",
            value,
            flags=re.IGNORECASE,
        )
    )


def _bounded_context_value(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("redacted"):
            return {"redacted": str(value["redacted"])[:80]}
        return {
            str(key)[:80]: _bounded_context_value(item)
            for key, item in list(value.items())[:8]
        }
    if isinstance(value, list):
        return [
            _bounded_context_value(item)
            for item in value[:_MAX_CONTEXT_VALUES]
        ]
    if isinstance(value, str):
        return value[:_MAX_CONTEXT_VALUE_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_CONTEXT_VALUE_LENGTH]


def _strict_bool(value: Any, field: str, *, default: bool = False) -> bool:
    """Accept an actual Boolean and reject truthy strings/numbers."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be boolean")


def _is_non_bool_int(value: Any) -> bool:
    """Return whether a value is an integer without Python bool coercion."""

    return isinstance(value, int) and not isinstance(value, bool)


def _read_only_context_field(
    field: Dict[str, Any],
    *,
    recommended_role: str,
    profile_sha256: str,
) -> Dict[str, Any]:
    include_values = recommended_role in _READ_ONLY_CONTEXT_ROLES_WITH_VALUES
    top_values = field.get("top_values", []) if include_values else []
    representative_values = (
        field.get("representative_values", []) if include_values else []
    )
    return {
        "source_profile_identity": {
            "profile_sha256": profile_sha256,
            "domain": str(field.get("domain", "")).strip(),
            "field": str(field.get("field", "")).strip(),
        },
        "recommended_role": recommended_role,
        "total_rows": int(field.get("total_rows", 0) or 0),
        "non_empty_count": int(field.get("non_empty_count", 0) or 0),
        "values_redacted": _strict_bool(
            field.get("values_redacted"),
            "field.values_redacted",
        )
        or not include_values,
        "top_values": _bounded_context_value(
            top_values[:_MAX_CONTEXT_VALUES]
            if isinstance(top_values, list)
            else []
        ),
        "representative_values": _bounded_context_value(
            representative_values[:_MAX_CONTEXT_VALUES]
            if isinstance(representative_values, list)
            else []
        ),
    }


def _mapping_is_dose_like(mapping: Dict[str, Any]) -> bool:
    role = re.sub(
        r"[\s_:/\\-]+",
        ".",
        str(mapping.get("recommended_role", "")).strip().casefold(),
    )
    source_field = str(mapping.get("source_field", "")).strip().casefold()
    return (
        ".dose" in role
        or role.endswith("dose")
        or "dose" in source_field
        or "剂量" in source_field
    )


def _append_mapping_quality_note(
    mapping: Dict[str, Any],
    *,
    action_code: str,
    uncertainty: str,
    user_action: str,
) -> None:
    actions = mapping.setdefault("quality_gate_actions", [])
    if action_code not in actions:
        actions.append(action_code)
    current_uncertainty = str(mapping.get("uncertainty", "")).strip()
    if uncertainty not in current_uncertainty:
        mapping["uncertainty"] = (
            f"{current_uncertainty}{uncertainty}"
            if current_uncertainty
            else uncertainty
        )
    current_user_action = str(mapping.get("user_action", "")).strip()
    if user_action not in current_user_action:
        mapping["user_action"] = (
            f"{current_user_action}{user_action}"
            if current_user_action
            else user_action
        )


class MonitoringAiServiceError(RuntimeError):
    pass


class MonitoringAiOutputValidationError(MonitoringAiServiceError):
    def __init__(
        self,
        message: str,
        *,
        diagnostics: Sequence[Dict[str, Any]] = (),
    ):
        super().__init__(message)
        self.diagnostics = tuple(dict(item) for item in diagnostics)


class MonitoringAiRuntimeUnavailableError(MonitoringAiServiceError):
    pass


class MonitoringAiResponseIdentityError(MonitoringAiServiceError):
    pass


class MonitoringAiTransportRejectedError(MonitoringAiServiceError):
    pass


@dataclass(frozen=True)
class MonitoringAiRuntimeBinding:
    profile_id: str
    provider: str
    model: str
    env: Dict[str, str]
    transport: str = MONITORING_PRODUCT_AI_TRANSPORT
    available: bool = True
    diagnostic: str = ""
    failure_code: str = ""

    @classmethod
    def unavailable(
        cls,
        diagnostic: str,
        *,
        failure_code: str = "ai_not_configured",
        transport: str = "",
    ) -> "MonitoringAiRuntimeBinding":
        return cls(
            profile_id="independent_ai_unavailable",
            provider="disabled",
            model="not_configured",
            env={},
            transport=transport,
            available=False,
            diagnostic=diagnostic.strip() or "independent AI is not configured",
            failure_code=failure_code,
        )


@dataclass(frozen=True)
class MonitoringAiRunResult:
    job: Optional[MonitoringAiJob]
    processed: bool
    lease_lost: bool = False


@dataclass(frozen=True)
class MonitoringAiDeterministicRepairResult:
    job: MonitoringAiJob
    candidate: MonitoringAiCandidate
    repair: Dict[str, Any]


class _ProviderEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=2, max_length=160)
    source_entry_id: str = Field(min_length=2, max_length=160)
    source_content_sha256: str = Field(min_length=64, max_length=64)
    locator: str = Field(min_length=2, max_length=1_000)
    quote: str = Field(default="", max_length=8_000)
    raw_fields: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_evidence_content(self) -> "_ProviderEvidence":
        if not self.quote.strip() and not self.raw_fields:
            raise ValueError("evidence requires quote or raw_fields")
        return self


class _ProviderClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=2, max_length=160)
    kind: MonitoringAiClaimKind
    text: str = Field(min_length=1, max_length=8_000)
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(default="", max_length=4_000)
    user_action: str = Field(default="", max_length=2_000)
    evidence_ids: List[str] = Field(min_length=1, max_length=20)


class _ProviderCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_type: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=20_000)
    structured_payload: Dict[str, Any] = Field(default_factory=dict)
    claims: List[_ProviderClaim] = Field(default_factory=list, max_length=100)
    evidence: List[_ProviderEvidence] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_graph_and_language(self) -> "_ProviderCandidate":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("candidate evidence IDs must be unique")
        claim_ids = [item.claim_id for item in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("candidate claim IDs must be unique")
        generated_text = "\n".join(
            [
                self.title,
                self.text,
                *[claim.text for claim in self.claims],
                *[claim.user_action for claim in self.claims],
            ]
        )
        if any(phrase in generated_text for phrase in _FORBIDDEN_DEFINITIVE_PHRASES):
            raise ValueError("provider output contains definitive approval language")
        return self


class _ProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    task_id: str
    task_type: MonitoringAiTaskType
    input_revision_sha256: str = Field(min_length=64, max_length=64)
    candidates: List[_ProviderCandidate] = Field(min_length=1, max_length=5)


class _StandardsReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_name: str = Field(min_length=2, max_length=160)
    reference_concept: str = Field(min_length=1, max_length=500)
    reference_only: Literal[True]
    uncertainty: str = Field(min_length=1, max_length=2_000)


class _TreatmentIdentityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["monitoring_treatment_identity_binding_v1"]
    binding_id: str = Field(min_length=2, max_length=160)
    source_domain: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=240)
    target_domain: str = Field(min_length=1, max_length=80)
    relationship_type: Literal[
        "subject_level_randomized_assignment",
        "subject_level_treatment_assignment",
        "protocol_defined_treatment_binding",
    ]
    join_keys: List[str] = Field(min_length=1, max_length=12)


class _FieldMappingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=240)
    recommended_role: str = Field(min_length=2, max_length=240)
    field_kind: MonitoringFieldKind
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(min_length=1, max_length=4_000)
    user_action: str = Field(min_length=1, max_length=2_000)
    related_fields: List[str] = Field(default_factory=list, max_length=100)
    evidence_ids: List[str] = Field(default_factory=list, max_length=50)
    standards_reference: Optional[_StandardsReference] = None
    derivation_lineage: Optional[Dict[str, Any]] = None
    object_identity: Literal[
        "not_applicable",
        "unresolved",
        "investigational_product",
        "placebo",
        "active_comparator",
        "background_therapy",
        "rescue_therapy",
        "concomitant_non_ip",
        "other_non_ip_treatment",
    ] = "not_applicable"
    object_identity_evidence_fields: List[str] = Field(
        default_factory=list,
        max_length=24,
    )
    object_identity_binding_id: str = Field(default="", max_length=160)
    validated_treatment_identity_binding: Optional[
        _TreatmentIdentityBinding
    ] = None
    dose_semantics: Literal[
        "not_applicable",
        "unresolved",
        "planned",
        "prescribed",
        "actual_administered",
        "dispensed",
        "returned",
        "duplicate_or_derived",
    ] = "not_applicable"
    quality_gate_actions: List[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_scientific_boundary(self) -> "_FieldMappingItem":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("field mapping evidence_ids must be unique")
        if len(self.object_identity_evidence_fields) != len(
            set(self.object_identity_evidence_fields)
        ):
            raise ValueError(
                "object_identity_evidence_fields must be unique"
            )
        if len(self.quality_gate_actions) != len(
            set(self.quality_gate_actions)
        ):
            raise ValueError("quality_gate_actions must be unique")
        validate_monitoring_mapping_semantics(
            domain=self.domain,
            source_field=self.source_field,
            recommended_role=self.recommended_role,
            field_kind=self.field_kind,
            standards_reference=(
                self.standards_reference.model_dump(mode="json")
                if self.standards_reference is not None
                else None
            ),
            derivation_lineage=self.derivation_lineage,
        )
        return self


class _FieldMappingOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=240)
    origin: Literal["deterministic_rule", "independent_ai"]
    rule_id: str = Field(default="", max_length=160)
    rule_version: str = Field(default="", max_length=160)
    rule_description: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def validate_origin(self) -> "_FieldMappingOrigin":
        rule_values = (
            self.rule_id.strip(),
            self.rule_version.strip(),
            self.rule_description.strip(),
        )
        if self.origin == "deterministic_rule" and not all(rule_values):
            raise ValueError(
                "deterministic mapping origin requires rule id, version and description"
            )
        if self.origin == "independent_ai" and any(rule_values):
            raise ValueError("AI mapping origin must not claim a deterministic rule")
        return self


class _ListingFieldMappingProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["monitoring_field_mapping_provenance_v1"]
    assembled_by: Literal["workbench_mapping_orchestrator"]
    field_origins: List[_FieldMappingOrigin] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "_ListingFieldMappingProvenance":
        pairs = [
            (item.domain.strip(), item.source_field.strip())
            for item in self.field_origins
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError("field mapping provenance pairs must be unique")
        return self


class _ListingFieldMappingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_mappings: List[_FieldMappingItem]
    mapping_provenance: Optional[_ListingFieldMappingProvenance] = None


class _ProtocolSourceConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    modalities: List[
        Literal["required", "optional", "prohibited"]
    ] = Field(min_length=2, max_length=3)
    status: Literal["requires_user_resolution"]
    evidence_ids: List[str] = Field(min_length=2, max_length=50)


class _ProtocolRepairTableBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["table"]
    table_index: int
    row_index: int
    row_evidence_ids: List[str]
    header_evidence_ids: List[str]


class _ProtocolRepairListBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["list"]
    list_bundle_id: str = Field(min_length=1, max_length=240)
    ancestor_title_evidence_id: str
    item_evidence_ids: List[str]


class _ProtocolRepairLineage(BaseModel):
    """Server-owned deterministic repair lineage for one protocol clause.

    Only the server writes this payload after provider schema validation;
    raw provider output containing it is rejected before normalization.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[PROTOCOL_STRUCTURAL_REPAIR_VERSION]
    original_evidence_ids: List[str]
    added_structural_context_ids: List[str]
    expanded_evidence_ids: List[str]
    bundle_bindings: List[
        Union[_ProtocolRepairTableBinding, _ProtocolRepairListBinding]
    ]


class _ProtocolClausePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str = Field(min_length=1, max_length=240)
    fact_type: str = Field(min_length=2, max_length=120)
    subject_scope: str = Field(min_length=1, max_length=2_000)
    conditions: List[str]
    time_windows: List[str]
    thresholds: List[str]
    exceptions: List[str]
    required_actions: List[str]
    evidence_ids: List[str] = Field(min_length=1, max_length=50)
    source_conflicts: List[_ProtocolSourceConflict] = Field(
        default_factory=list,
        max_length=20,
    )
    # Server-owned deterministic structural repair lineage. Provider output
    # containing this field is rejected before normalization.
    repair_lineage: Optional[_ProtocolRepairLineage] = None


class _RuleTemplateRecommendationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_type: str = Field(min_length=2, max_length=120)
    rule_family: str = Field(min_length=2, max_length=120)
    rationale: str = Field(min_length=1, max_length=4_000)
    tradeoffs: List[str] = Field(default_factory=list, max_length=10)
    deterministic_template: Dict[str, Any]
    evidence_ids: List[str] = Field(min_length=2, max_length=50)


class _CrossTableCluePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=240)
    domains: List[str] = Field(min_length=2, max_length=30)
    observations: List[str] = Field(min_length=1)
    temporal_relationships: List[str]
    data_gaps: List[str]
    recommended_review: str = Field(min_length=1, max_length=4_000)
    evidence_ids: List[str] = Field(min_length=1, max_length=50)


class _RiskEvidenceSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(min_length=1, max_length=240)
    facts: List[str] = Field(min_length=1)
    inferences: List[str]
    data_gaps: List[str]
    recommended_actions: List[str]
    evidence_ids: List[str] = Field(min_length=1, max_length=50)


class _RiskQuestionAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=8_000)
    answer: str = Field(min_length=1, max_length=20_000)
    evidence_limitations: List[str]
    follow_up_questions: List[str]
    evidence_ids: List[str] = Field(min_length=1, max_length=50)


class _QueryExplanationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["query", "explanation"]
    observation: str = Field(min_length=1, max_length=8_000)
    request_or_explanation: str = Field(min_length=1, max_length=20_000)
    requested_follow_up: str = Field(default="", max_length=8_000)
    evidence_ids: List[str] = Field(min_length=1, max_length=50)


STRUCTURED_PAYLOAD_MODEL_BY_TASK: Dict[
    MonitoringAiTaskType,
    Type[BaseModel],
] = {
    MonitoringAiTaskType.LISTING_FIELD_MAPPING: _ListingFieldMappingPayload,
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING: _ProtocolClausePayload,
    MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION: (
        _RuleTemplateRecommendationPayload
    ),
    MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS: _CrossTableCluePayload,
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY: _RiskEvidenceSummaryPayload,
    MonitoringAiTaskType.RISK_QUESTION_ANSWER: _RiskQuestionAnswerPayload,
    MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES: (_QueryExplanationPayload),
}


def resolve_monitoring_ai_runtime() -> MonitoringAiRuntimeBinding:
    try:
        store = runtime_ai_role_settings_store()
        binding = store.binding(INDEPENDENT_AI_ROLE)
        profile = store.provider_store.profile(binding.profile_id)
        env = store.role_env(INDEPENDENT_AI_ROLE)
        provider = env.get("WORKBENCH_AI_PROVIDER", "").strip()
        model = env.get("WORKBENCH_AI_MODEL", "").strip()
        transport = (
            env.get("WORKBENCH_AI_TRANSPORT", "").strip()
            or profile.transport.strip()
        )
        if (
            not binding.enabled
            or not binding.profile_id.strip()
            or not provider
            or provider == "disabled"
            or not model
        ):
            return MonitoringAiRuntimeBinding.unavailable(
                "independent AI role or provider profile is disabled",
                transport=transport,
            )
        if transport != MONITORING_PRODUCT_AI_TRANSPORT:
            return MonitoringAiRuntimeBinding.unavailable(
                "medical monitoring product AI rejects non-openai_compatible "
                f"transport: {transport or 'missing'}",
                failure_code="ai_transport_rejected",
                transport=transport,
            )
        if (
            profile.transport.strip() != transport
            or profile.provider.strip() != provider
            or profile.model.strip() != model
        ):
            return MonitoringAiRuntimeBinding.unavailable(
                "independent AI role/profile runtime does not match the shared "
                "selector binding",
                failure_code="ai_configuration_error",
                transport=transport,
            )
        expected_response_model = env.get(
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL",
            "",
        ).strip()
        if expected_response_model != model:
            return MonitoringAiRuntimeBinding.unavailable(
                "independent AI expected response model does not match the "
                "selected model",
                failure_code="response_model_identity",
                transport=transport,
            )
        status = ai_gateway_status_from_env(env)
        if (
            status.get("configured") is not True
            or status.get("semantic_ai_tasks_enabled") is not True
            or status.get("transport") != MONITORING_PRODUCT_AI_TRANSPORT
            or status.get("provider") != provider
            or status.get("model") != model
        ):
            reasons = [
                *[
                    str(item)
                    for item in status.get("route_validation_errors", [])
                    if str(item).strip()
                ],
                *[
                    f"missing {item}"
                    for item in status.get("missing_env", [])
                    if str(item).strip()
                ],
            ]
            return MonitoringAiRuntimeBinding.unavailable(
                "independent AI role/profile is not currently runnable"
                + (f": {'; '.join(reasons)}" if reasons else ""),
                failure_code="ai_not_configured",
                transport=transport,
            )
        return MonitoringAiRuntimeBinding(
            profile_id=binding.profile_id,
            provider=provider,
            model=model,
            env=env,
            transport=transport,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        return MonitoringAiRuntimeBinding.unavailable(
            f"independent AI runtime discovery failed: {type(exc).__name__}: {exc}"
        )


class MonitoringAiService:
    """Product-AI service for medical monitoring candidate generation.

    The service owns prompt/output contracts and worker orchestration. It never
    mutates formal risk status; only the monitoring repository stores proposed
    AI candidates and their evidence graph.
    """

    def __init__(
        self,
        repository: MonitoringAiRepository,
        *,
        runtime_resolver: Callable[[], MonitoringAiRuntimeBinding] = (
            resolve_monitoring_ai_runtime
        ),
        provider_factory: Callable[[Dict[str, str]], AiProvider] = (
            configured_ai_provider_from_env
        ),
        current_revision_resolver: Optional[Callable[[MonitoringAiJob], str]] = None,
    ):
        self.repository = repository
        self.runtime_resolver = runtime_resolver
        self.provider_factory = provider_factory
        self.current_revision_resolver = current_revision_resolver or (
            lambda job: job.input_revision_sha256
        )

    def submit_task(
        self,
        *,
        project_id: str,
        task_type: MonitoringAiTaskType,
        input_revision: MonitoringAiInputRevision,
        input_payload: Dict[str, Any],
        business_key: str,
        prompt_version: str = "",
        max_attempts: int = 2,
    ) -> MonitoringAiJob:
        self._validate_input_payload(
            task_type,
            project_id,
            input_revision,
            input_payload,
        )
        runtime = self.runtime_resolver()
        request = MonitoringAiJobCreate(
            project_id=project_id,
            task_type=task_type,
            input_revision=input_revision,
            input_payload=input_payload,
            prompt_version=(
                prompt_version.strip() or PROMPT_VERSION_BY_TASK[task_type]
            ),
            profile_id=runtime.profile_id,
            provider=runtime.provider,
            requested_model=runtime.model,
            max_attempts=max_attempts,
            business_key=business_key,
        )
        return self._create_job(request)

    def _create_job(
        self,
        request: MonitoringAiJobCreate,
    ) -> MonitoringAiJob:
        job = self.repository.create_or_get(request)
        self.repository.mark_stale(
            request.project_id,
            business_key=request.business_key,
            current_input_revision_sha256=job.input_revision_sha256,
        )
        self.repository.supersede_business_key_except(
            request.project_id,
            business_key=request.business_key,
            current_job_id=job.job_id,
            reason=(
                "任务输入、提示词、产品模型或执行配置已有更新，"
                "旧候选不再代表当前合同。"
            ),
        )
        return job

    def submit_listing_field_mapping(
        self,
        *,
        project_id: str,
        input_revision: MonitoringAiInputRevision,
        field_profile: Dict[str, Any],
        business_key: str = "listing-field-mapping",
        prompt_version: str = "",
        max_attempts: int = 2,
    ) -> MonitoringAiJob:
        effective_field_profile = deepcopy(field_profile)
        effective_field_profile["mapping_contract_versions"] = {
            "deterministic_metadata_mapping": (
                DETERMINISTIC_METADATA_MAPPING_VERSION
            ),
            "role_catalog": ROLE_CATALOG_VERSION,
            "semantic_rules": RULE_CATALOG_VERSION,
        }
        effective_revision = monitoring_revision_with_field_profile(
            input_revision,
            effective_field_profile["profile_sha256"],
        )
        effective_prompt_version = (
            prompt_version.strip()
            or PROMPT_VERSION_BY_TASK[MonitoringAiTaskType.LISTING_FIELD_MAPPING]
        )
        self._validate_input_payload(
            MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            project_id,
            effective_revision,
            {"field_profile": effective_field_profile},
        )
        _, remaining_fields = partition_metadata_fields(
            effective_field_profile["fields"]
        )
        if not remaining_fields:
            return self._create_job(
                MonitoringAiJobCreate(
                    project_id=project_id,
                    task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
                    input_revision=effective_revision,
                    input_payload={"field_profile": effective_field_profile},
                    prompt_version=effective_prompt_version,
                    profile_id=DETERMINISTIC_METADATA_PROFILE_ID,
                    provider=DETERMINISTIC_METADATA_PROVIDER,
                    requested_model=DETERMINISTIC_METADATA_MODEL,
                    max_attempts=max_attempts,
                    business_key=business_key,
                )
            )
        return self.submit_task(
            project_id=project_id,
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            input_revision=effective_revision,
            input_payload={"field_profile": effective_field_profile},
            business_key=business_key,
            prompt_version=effective_prompt_version,
            max_attempts=max_attempts,
        )

    def submit_listing_field_mapping_chunks(
        self,
        *,
        project_id: str,
        input_revision: MonitoringAiInputRevision,
        field_profile: Dict[str, Any],
        chunk_size: int = DEFAULT_FIELD_MAPPING_CHUNK_SIZE,
        prompt_version: str = "",
        max_attempts: int = 2,
    ) -> Tuple[MonitoringAiJob, ...]:
        if (
            not _is_non_bool_int(chunk_size)
            or not 1 <= chunk_size <= 12
        ):
            raise ValueError(
                "field mapping chunk_size must be an integer from 1 to 12"
            )
        self._validate_input_payload(
            MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            project_id,
            monitoring_revision_with_field_profile(
                input_revision,
                field_profile["profile_sha256"],
            ),
            {"field_profile": field_profile},
        )
        fields_by_domain: Dict[str, List[Dict[str, Any]]] = {}
        for field in field_profile["fields"]:
            domain = str(field["domain"]).strip()
            fields_by_domain.setdefault(domain, []).append(deepcopy(field))
        for domain_fields in fields_by_domain.values():
            domain_fields.sort(
                key=lambda item: (
                    str(item["field"]).strip().casefold(),
                    str(item["field"]).strip(),
                )
            )

        batch_id = str(field_profile["batch_id"]).strip()
        full_profile_sha256 = _require_service_sha256(
            field_profile["profile_sha256"],
            "field_profile.profile_sha256",
        )
        full_input_sha256 = _require_service_sha256(
            field_profile["input_sha256"],
            "field_profile.input_sha256",
        )
        full_field_count = len(field_profile["fields"])
        jobs: List[MonitoringAiJob] = []
        for domain in sorted(
            fields_by_domain,
            key=lambda value: (value.casefold(), value),
        ):
            domain_fields = fields_by_domain[domain]
            chunk_total = (len(domain_fields) + chunk_size - 1) // chunk_size
            for zero_based_index in range(chunk_total):
                chunk_index = zero_based_index + 1
                start = zero_based_index * chunk_size
                chunk_fields = domain_fields[start : start + chunk_size]
                chunk_profile = {
                    key: deepcopy(value)
                    for key, value in field_profile.items()
                    if key
                    not in {
                        "fields",
                        "relationships",
                        "treatment_identity_bindings",
                    }
                }
                chunk_field_names = {
                    str(item["field"]).strip() for item in chunk_fields
                }
                chunk_relationships = [
                    deepcopy(relationship)
                    for relationship in field_profile.get("relationships", [])
                    if (
                        str(relationship.get("domain", "")).strip() == domain
                        and {
                            str(relationship.get("left_field", "")).strip(),
                            str(relationship.get("right_field", "")).strip(),
                        }.intersection(chunk_field_names)
                    )
                ]
                chunk_profile.update(
                    {
                        "scope": "complete_profile_chunk",
                        "full_profile_sha256": full_profile_sha256,
                        "full_input_sha256": full_input_sha256,
                        "full_field_count": full_field_count,
                        "domain": domain,
                        "domain_field_count": len(domain_fields),
                        # The model may reference lineage fields elsewhere in the
                        # same domain, but it may only emit mappings for `fields`.
                        "domain_field_names": [
                            str(item["field"]).strip()
                            for item in domain_fields
                        ],
                        "chunk_index": chunk_index,
                        "chunk_total": chunk_total,
                        "chunk_size_limit": chunk_size,
                        "fields": chunk_fields,
                        "relationships": chunk_relationships,
                        "read_only_domain_context_profiles": [
                            deepcopy(field)
                            for field, _ in partition_metadata_fields(
                                domain_fields
                            )[0]
                        ],
                        "treatment_identity_bindings": [
                            deepcopy(binding)
                            for binding in field_profile.get(
                                "treatment_identity_bindings",
                                [],
                            )
                            if str(
                                binding.get("target_domain", "")
                            ).strip()
                            == domain
                        ],
                        "treatment_identity_binding_source_pairs": [
                            {
                                "domain": str(
                                    binding.get("source_domain", "")
                                ).strip(),
                                "field": str(
                                    binding.get("source_field", "")
                                ).strip(),
                            }
                            for binding in field_profile.get(
                                "treatment_identity_bindings",
                                [],
                            )
                            if str(
                                binding.get("target_domain", "")
                            ).strip()
                            == domain
                        ],
                    }
                )
                business_key = (
                    "listing-field-mapping:"
                    f"{batch_id}:{domain}:"
                    f"{chunk_index:04d}-of-{chunk_total:04d}"
                )
                jobs.append(
                    self.submit_listing_field_mapping(
                        project_id=project_id,
                        input_revision=input_revision,
                        field_profile=chunk_profile,
                        business_key=business_key,
                        prompt_version=prompt_version,
                        max_attempts=max_attempts,
                    )
                )
        return tuple(jobs)

    def repair_failed_v7_deterministic_mapping(
        self,
        *,
        project_id: str,
        job_id: str,
        expected_batch_id: str,
        expected_input_revision_sha256: str,
        expected_full_profile_sha256: str,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> MonitoringAiDeterministicRepairResult:
        project_id = project_id.strip()
        job_id = job_id.strip()
        expected_batch_id = expected_batch_id.strip()
        expected_input_revision_sha256 = _require_service_sha256(
            expected_input_revision_sha256,
            "expected_input_revision_sha256",
        )
        expected_full_profile_sha256 = _require_service_sha256(
            expected_full_profile_sha256,
            "expected_full_profile_sha256",
        )
        actor = actor.strip()
        reason = reason.strip()
        idempotency_key = idempotency_key.strip()
        if not all(
            (
                project_id,
                job_id,
                expected_batch_id,
                actor,
                reason,
                idempotency_key,
            )
        ):
            raise ValueError(
                "deterministic repair identity, actor and reason are required"
            )
        request_identity = {
            "project_id": project_id,
            "job_id": job_id,
            "expected_batch_id": expected_batch_id,
            "expected_input_revision_sha256": (
                expected_input_revision_sha256
            ),
            "expected_full_profile_sha256": (
                expected_full_profile_sha256
            ),
            "actor": actor,
            "reason": reason,
            "idempotency_key": idempotency_key,
        }
        request_sha256 = content_sha256(request_identity)
        existing = self.repository.deterministic_repair_by_idempotency(
            project_id,
            idempotency_key,
        )
        if existing is not None:
            if (
                existing["request_sha256"] != request_sha256
                or existing["job_id"] != job_id
            ):
                raise MonitoringAiStateConflictError(
                    "deterministic repair idempotency key has different meaning"
                )
            repaired_job = self.repository.get(project_id, job_id)
            candidates = self.repository.candidates(project_id, job_id)
            if (
                repaired_job.status.value != "completed"
                or len(candidates) != 1
                or candidates[0].candidate_id != existing["candidate_id"]
            ):
                raise MonitoringAiStateConflictError(
                    "deterministic repair replay found inconsistent persisted state"
                )
            return MonitoringAiDeterministicRepairResult(
                job=repaired_job,
                candidate=candidates[0],
                repair=existing,
            )

        job = self.repository.get(project_id, job_id)
        if (
            job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING
            or job.status.value != "failed"
            or job.failure_code != "invalid_ai_output"
            or job.prompt_version != LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION
        ):
            raise MonitoringAiStateConflictError(
                "only failed v7 listing invalid_ai_output jobs are repairable"
            )
        if job.input_revision_sha256 != expected_input_revision_sha256:
            raise MonitoringAiStateConflictError(
                "deterministic repair input revision is stale"
            )
        if (
            job.input_revision.revision_sha256
            != job.input_revision_sha256
        ):
            raise MonitoringAiStateConflictError(
                "deterministic repair job revision identity is inconsistent"
            )

        input_payload = self.repository.input_payload(project_id, job_id)
        if content_sha256(input_payload) != job.input_payload_sha256:
            raise MonitoringAiStateConflictError(
                "deterministic repair input payload identity is inconsistent"
            )
        try:
            self._validate_input_payload(
                job.task_type,
                project_id,
                job.input_revision,
                input_payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringAiStateConflictError(
                f"deterministic repair input contract is invalid: {exc}"
            ) from exc
        profile = input_payload["field_profile"]
        if profile.get("scope") != "complete_profile_chunk":
            raise MonitoringAiStateConflictError(
                "deterministic repair requires a complete profile chunk"
            )
        if (
            str(profile.get("batch_id", "")).strip()
            != expected_batch_id
            or str(profile.get("project_id", "")).strip() != project_id
            or profile.get("profile_sha256")
            != expected_full_profile_sha256
            or profile.get("full_profile_sha256")
            != expected_full_profile_sha256
        ):
            raise MonitoringAiStateConflictError(
                "deterministic repair batch or field profile identity drifted"
            )
        expected_business_key = (
            "listing-field-mapping:"
            f"{expected_batch_id}:{str(profile['domain']).strip()}:"
            f"{int(profile['chunk_index']):04d}-of-"
            f"{int(profile['chunk_total']):04d}"
        )
        if job.business_key != expected_business_key:
            raise MonitoringAiStateConflictError(
                "deterministic repair business key does not match its chunk"
            )
        fields = profile["fields"]
        deterministic, remaining = partition_metadata_fields(fields)
        if remaining or len(deterministic) != len(fields):
            raise MonitoringAiStateConflictError(
                "deterministic repair refuses semantic, mixed or ambiguous fields"
            )
        if self.repository.candidates(project_id, job_id):
            raise MonitoringAiStateConflictError(
                "deterministic repair requires a job with no candidates"
            )

        output = {
            "schema_version": MONITORING_AI_SCHEMA_VERSION,
            "task_id": job.job_id,
            "task_type": job.task_type.value,
            "input_revision_sha256": job.input_revision_sha256,
            "candidates": [
                {
                    "candidate_type": "listing_field_mapping_set",
                    "title": "技术元数据确定性映射",
                    "text": (
                        "本组字段由工作台确定性技术规则生成，"
                        "未调用独立 AI。"
                    ),
                    "structured_payload": {"field_mappings": []},
                    "claims": [],
                    "evidence": [],
                }
            ],
        }
        candidate = self._parse_provider_output(
            job,
            output,
            input_payload,
        )[0]
        evidence = tuple(
            item.model_copy(
                update={
                    "raw_fields": {
                        **item.raw_fields,
                        "provenance": "deterministic_rule",
                        "deterministic_rule_version": (
                            DETERMINISTIC_METADATA_MAPPING_VERSION
                        ),
                        "ai_inference_used": False,
                        "migration_reason": (
                            LEGACY_V7_DETERMINISTIC_REPAIR_REASON
                        ),
                    }
                }
            )
            for item in candidate.evidence
        )
        candidate = candidate.model_copy(update={"evidence": evidence})
        provenance = {
            "schema_version": (
                DETERMINISTIC_METADATA_PROVENANCE_SCHEMA_VERSION
            ),
            "provenance": "deterministic_rule",
            "deterministic_rule_version": (
                DETERMINISTIC_METADATA_MAPPING_VERSION
            ),
            "ai_inference_used": False,
            "migration_reason": LEGACY_V7_DETERMINISTIC_REPAIR_REASON,
            "field_origins": candidate.structured_payload[
                "mapping_provenance"
            ]["field_origins"],
        }
        raw_output = {
            "schema_version": "monitoring_ai_deterministic_repair_v1",
            "job_id": job.job_id,
            "input_revision_sha256": job.input_revision_sha256,
            "input_payload_sha256": job.input_payload_sha256,
            "prompt_version": job.prompt_version,
            "requested_model": job.requested_model,
            "response_model": DETERMINISTIC_METADATA_MODEL,
            "provenance": provenance,
            "candidate": candidate.model_dump(mode="json"),
        }
        repaired_job, repair = (
            self.repository.complete_failed_v7_deterministic_mapping(
                job,
                candidate=candidate,
                response_model=DETERMINISTIC_METADATA_MODEL,
                raw_output=raw_output,
                provenance=provenance,
                actor=actor,
                reason=reason,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
        )
        persisted_candidates = self.repository.candidates(
            project_id,
            job_id,
        )
        if (
            len(persisted_candidates) != 1
            or persisted_candidates[0].candidate_id
            != repair["candidate_id"]
        ):
            raise MonitoringAiStateConflictError(
                "deterministic repair candidate persistence is inconsistent"
            )
        return MonitoringAiDeterministicRepairResult(
            job=repaired_job,
            candidate=persisted_candidates[0],
            repair=repair,
        )

    def run_next(self, owner: str) -> MonitoringAiRunResult:
        job = self.repository.claim_next(owner)
        if job is None:
            return MonitoringAiRunResult(job=None, processed=False)

        try:
            current_revision = self.current_revision_resolver(job)
            if current_revision != job.input_revision_sha256:
                return self._stale_claimed_job(
                    job,
                    owner=owner,
                    request_payload={"job_id": job.job_id},
                    response_payload=None,
                    failure_message=(
                        "monitoring AI input revision changed before execution"
                    ),
                    outcome="stale_input",
                )

            input_payload = self.repository.input_payload(
                job.project_id,
                job.job_id,
            )
            if self._is_deterministic_only_mapping(input_payload, job):
                return self._complete_deterministic_mapping(
                    job,
                    owner=owner,
                    input_payload=input_payload,
                )

            runtime = self.runtime_resolver()
            if not runtime.available:
                return self._fail_claimed_job(
                    job,
                    owner=owner,
                    request_payload={"job_id": job.job_id},
                    response_payload=None,
                    failure_code=(
                        runtime.failure_code.strip() or "ai_not_configured"
                    ),
                    failure_message=runtime.diagnostic,
                    retryable=False,
                    outcome="configuration_error",
                )
            self._validate_runtime_transport(runtime)
            self._validate_runtime_matches_job(job, runtime)
            provider = self.provider_factory(
                self._monitoring_provider_env(runtime.env)
            )
            if isinstance(provider, DisabledAiProvider):
                raise MonitoringAiRuntimeUnavailableError(
                    "configured independent AI provider is unavailable"
                )
            self._validate_provider_matches_job(job, provider)

            envelope = self._build_prompt_envelope(job, input_payload)
            initial_output = self._run_with_heartbeat(
                job,
                owner,
                provider,
                envelope,
            )
            outputs: List[Any] = [initial_output]
            stale_result = self._fail_if_revision_changed(
                job,
                owner=owner,
                request_payload={"envelope": envelope.payload},
                response_payload={"provider_outputs": outputs},
                stage="after_initial_provider_call",
                response_model=self._provider_response_model_without_assertion(
                    provider
                ),
            )
            if stale_result is not None:
                return stale_result
            repaired = False
            try:
                candidates = self._parse_provider_output(
                    job,
                    initial_output,
                    input_payload,
                )
            except (
                MonitoringAiOutputValidationError,
                ValidationError,
                ValueError,
            ) as first_error:
                repaired = True
                validation_errors = self._controlled_validation_error_text(
                    first_error
                )
                validation_diagnostics = (
                    self._structured_validation_diagnostics(first_error)
                )
                repair_envelope = self._build_repair_envelope(
                    job,
                    input_payload,
                    initial_output,
                    validation_errors,
                    validation_diagnostics,
                )
                repaired_output = self._run_with_heartbeat(
                    job,
                    owner,
                    provider,
                    repair_envelope,
                )
                outputs.append(repaired_output)
                stale_result = self._fail_if_revision_changed(
                    job,
                    owner=owner,
                    request_payload={
                        "envelope": envelope.payload,
                        "repair_envelope": repair_envelope.payload,
                    },
                    response_payload={"provider_outputs": outputs},
                    stage="after_repair_provider_call",
                    response_model=(
                        self._provider_response_model_without_assertion(provider)
                    ),
                )
                if stale_result is not None:
                    return stale_result
                try:
                    candidates = self._parse_provider_output(
                        job,
                        repaired_output,
                        input_payload,
                    )
                except (
                    MonitoringAiOutputValidationError,
                    ValidationError,
                    ValueError,
                ) as exc:
                    residual_diagnostics = (
                        self._structured_validation_diagnostics(exc)
                    )
                    response_payload: Dict[str, Any] = {
                        "provider_outputs": outputs
                    }
                    if residual_diagnostics:
                        response_payload["validation_diagnostics"] = (
                            residual_diagnostics
                        )
                    failure_detail = self._controlled_validation_error_text(
                        exc
                    )
                    if residual_diagnostics:
                        failure_detail += (
                            "; residual_validation_diagnostics="
                            + canonical_json(residual_diagnostics)
                        )
                    return self._fail_claimed_job(
                        job,
                        owner=owner,
                        request_payload={
                            "envelope": envelope.payload,
                            "repair_envelope": repair_envelope.payload,
                        },
                        response_payload=response_payload,
                        failure_code="invalid_ai_output",
                        failure_message=(
                            "provider output remained invalid after one "
                            f"controlled repair: {failure_detail}"
                        ),
                        retryable=False,
                        outcome="invalid_output",
                        response_model=self._response_model(provider, job),
                    )

            response_model = self._response_model(provider, job)
            stale_result = self._fail_if_revision_changed(
                job,
                owner=owner,
                request_payload={
                    "envelope": envelope.payload,
                    "repair_used": repaired,
                },
                response_payload={"provider_outputs": outputs},
                stage="before_attempt_and_completion",
                response_model=response_model,
            )
            if stale_result is not None:
                return stale_result
            self.repository.heartbeat(job.project_id, job.job_id, owner)
            self.repository.record_attempt(
                job,
                owner=owner,
                request_payload={
                    "envelope": envelope.payload,
                    "repair_used": repaired,
                },
                response_payload={"provider_outputs": outputs},
                response_model=response_model,
                outcome="success_repaired" if repaired else "success",
            )
            completed = self.repository.complete(
                job,
                owner=owner,
                response_model=response_model,
                raw_output=outputs[-1],
                candidates=candidates,
            )
            return MonitoringAiRunResult(job=completed, processed=True)
        except MonitoringAiStateConflictError:
            return MonitoringAiRunResult(
                job=self._current_job_or_claim(job),
                processed=False,
                lease_lost=True,
            )
        except MonitoringAiRuntimeUnavailableError as exc:
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code="ai_not_configured",
                failure_message=str(exc),
                retryable=False,
                outcome="configuration_error",
            )
        except MonitoringAiTransportRejectedError as exc:
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code="ai_transport_rejected",
                failure_message=str(exc),
                retryable=False,
                outcome="transport_rejected",
            )
        except AiGatewayConfigurationError as exc:
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code="ai_configuration_error",
                failure_message=str(exc),
                retryable=False,
                outcome="configuration_error",
            )
        except MonitoringAiResponseIdentityError as exc:
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code="response_model_identity",
                failure_message=str(exc),
                retryable=False,
                outcome="identity_error",
            )
        except AiProviderRuntimeError as exc:
            identity_error = "identity" in str(exc).casefold()
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code=(
                    "response_model_identity"
                    if identity_error
                    else "provider_runtime_error"
                ),
                failure_message=str(exc),
                retryable=not identity_error,
                outcome="provider_error",
            )
        except Exception as exc:
            return self._fail_claimed_job(
                job,
                owner=owner,
                request_payload={"job_id": job.job_id},
                response_payload=None,
                failure_code="monitoring_ai_worker_error",
                failure_message=f"{type(exc).__name__}: {exc}",
                retryable=False,
                outcome="worker_error",
            )

    @staticmethod
    def _is_deterministic_only_mapping(
        input_payload: Dict[str, Any],
        job: MonitoringAiJob,
    ) -> bool:
        if job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            return False
        field_profile = input_payload.get("field_profile")
        if not isinstance(field_profile, dict):
            return False
        fields = field_profile.get("fields")
        if not isinstance(fields, list) or not fields:
            return False
        _, remaining = partition_metadata_fields(fields)
        return not remaining

    def _complete_deterministic_mapping(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        input_payload: Dict[str, Any],
    ) -> MonitoringAiRunResult:
        output = {
            "schema_version": MONITORING_AI_SCHEMA_VERSION,
            "task_id": job.job_id,
            "task_type": job.task_type.value,
            "input_revision_sha256": job.input_revision_sha256,
            "candidates": [
                {
                    "candidate_type": "listing_field_mapping_set",
                    "title": "技术元数据确定性映射",
                    "text": (
                        "本组字段由工作台确定性技术规则生成，"
                        "未调用独立 AI。"
                    ),
                    "structured_payload": {"field_mappings": []},
                    "claims": [],
                    "evidence": [],
                }
            ],
        }
        candidates = self._parse_provider_output(
            job,
            output,
            input_payload,
        )
        stale_result = self._fail_if_revision_changed(
            job,
            owner=owner,
            request_payload={
                "execution_origin": "deterministic_rule",
                "provider_called": False,
                "rule_version": DETERMINISTIC_METADATA_MAPPING_VERSION,
            },
            response_payload=output,
            stage="before_deterministic_completion",
            response_model=job.requested_model,
        )
        if stale_result is not None:
            return stale_result
        self.repository.heartbeat(job.project_id, job.job_id, owner)
        self.repository.record_attempt(
            job,
            owner=owner,
            request_payload={
                "execution_origin": "deterministic_rule",
                "provider_called": False,
                "rule_version": DETERMINISTIC_METADATA_MAPPING_VERSION,
            },
            response_payload=output,
            response_model=job.requested_model,
            outcome="success_deterministic",
        )
        completed = self.repository.complete(
            job,
            owner=owner,
            response_model=job.requested_model,
            raw_output={
                "execution_origin": "deterministic_rule",
                "provider_called": False,
                "rule_version": DETERMINISTIC_METADATA_MAPPING_VERSION,
                "output": output,
            },
            candidates=candidates,
        )
        return MonitoringAiRunResult(job=completed, processed=True)

    @staticmethod
    def _provider_input_payload(
        job: MonitoringAiJob,
        input_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if (
            job.task_type
            == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ):
            return MonitoringAiService._focused_protocol_provider_payload(
                input_payload
            )
        if job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            return input_payload
        result = deepcopy(input_payload)
        profile = result["field_profile"]
        deterministic, remaining = partition_metadata_fields(profile["fields"])
        remaining_pairs = {
            (
                str(field["domain"]).strip(),
                str(field["field"]).strip(),
            )
            for field in remaining
        }
        profile["fields"] = [deepcopy(field) for field in remaining]
        profile["required_output_field_names"] = [
            str(field["field"]).strip() for field in remaining
        ]
        profile["relationships"] = [
            deepcopy(relationship)
            for relationship in profile.get("relationships", [])
            if (
                (
                    str(relationship.get("domain", "")).strip(),
                    str(relationship.get("left_field", "")).strip(),
                )
                in remaining_pairs
                or (
                    str(relationship.get("domain", "")).strip(),
                    str(relationship.get("right_field", "")).strip(),
                )
                in remaining_pairs
            )
        ]
        profile["inference_scope"] = "remaining_semantic_fields"
        profile["original_chunk_field_count"] = (
            len(deterministic) + len(remaining)
        )
        profile["deterministic_metadata_field_count"] = len(deterministic)
        context_profiles = [
            deepcopy(field)
            for field in profile.get(
                "read_only_domain_context_profiles",
                [],
            )
            if isinstance(field, dict)
        ]
        context_by_pair: Dict[
            Tuple[str, str],
            Tuple[Dict[str, Any], Any],
        ] = {
            (
                str(field["domain"]).strip(),
                str(field["field"]).strip(),
            ): (field, decision)
            for field, decision in deterministic
        }
        for field in context_profiles:
            decision = deterministic_metadata_decision(
                str(field.get("domain", "")).strip(),
                str(field.get("field", "")).strip(),
            )
            if decision is None:
                continue
            context_by_pair.setdefault(
                (
                    str(field.get("domain", "")).strip(),
                    str(field.get("field", "")).strip(),
                ),
                (field, decision),
            )
        profile["read_only_domain_context"] = {
            "policy": (
                "These deterministic form/page-name and system-metadata profiles "
                "are read-only domain context. Use them to disambiguate treatment "
                "identity, dose semantics and scale context. Never emit field "
                "mappings for these system-owned fields; the workbench deterministically "
                "maps them outside the AI."
            ),
            "fields": [
                _read_only_context_field(
                    field,
                    recommended_role=decision.recommended_role,
                    profile_sha256=_require_service_sha256(
                        profile.get("profile_sha256"),
                        "field_profile.profile_sha256",
                    ),
                )
                for field, decision in context_by_pair.values()
            ],
        }
        profile.pop("read_only_domain_context_profiles", None)
        chunk_domain = str(profile.get("domain", "")).strip()
        domain_field_names = profile.get("domain_field_names")
        if chunk_domain and isinstance(domain_field_names, list):
            profile["domain_field_names"] = [
                str(field_name).strip()
                for field_name in domain_field_names
                if str(field_name).strip()
                and deterministic_metadata_decision(
                    chunk_domain,
                    str(field_name),
                )
                is None
            ]
        return result

    @staticmethod
    def _focused_protocol_provider_payload(
        input_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the deterministic focused evidence view for protocol jobs.

        The persisted payload keeps its identity and full authoritative packet;
        the provider sees only the focused structural bundles plus an explicit
        evidence budget, so requests and repairs stay materially smaller.
        """

        context = input_payload.get("context")
        evidence_packet = input_payload.get("evidence_packet")
        if (
            not isinstance(context, dict)
            or context.get("evidence_packet_version")
            != PROTOCOL_EVIDENCE_PACKET_VERSION
            or not isinstance(evidence_packet, list)
        ):
            return input_payload
        result = deepcopy(input_payload)
        conflict_evidence_ids = [
            str(evidence_id).strip()
            for conflict in context.get("detected_source_conflicts") or ()
            if isinstance(conflict, dict)
            for evidence_id in (conflict.get("evidence_ids") or ())
            if str(evidence_id).strip()
        ]
        focused_packet = focus_protocol_provider_evidence(
            evidence_packet,
            conflict_evidence_ids=conflict_evidence_ids,
        )
        result["evidence_packet"] = list(focused_packet)
        focus_context = result["context"]
        focus_context["provider_evidence_focus"] = {
            "scope": "focused_structural_bundles",
            "full_document_coverage_asserted": False,
            "retained_evidence_count": len(focused_packet),
            "source_evidence_count": len(evidence_packet),
            "max_evidence_ids_per_candidate": (
                MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS
            ),
            "bundle_policy": (
                "same-row cells with available headers; "
                "selected list items with their stable list bundle identity "
                "and unique ancestor title; title-only stays title-only; "
                "exact conflict evidence sets"
            ),
        }
        focus_context["retrieval_scope"] = "focused_structural_bundles"
        instruction = str(focus_context.get("instruction") or "").strip()
        if instruction:
            focus_context["instruction"] = (
                instruction
                + " 当前证据包是经确定性聚焦的结构化证据视图，已保留表格"
                "同行/表头完整束；列表仅保留已选条目及其唯一上级标题，"
                "不枚举同级未选条目；它不是对整份方案的逐字核验。"
                "每个候选 structured_payload 引用的不同 evidence_id（含"
                "source_conflicts 的 evidence_ids）总计不得超过 "
                f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS} 个。"
            )
        return result

    def _build_prompt_envelope(
        self,
        job: MonitoringAiJob,
        input_payload: Dict[str, Any],
    ) -> AiPromptEnvelope:
        provider_input_payload = self._provider_input_payload(job, input_payload)
        candidate_types = TASK_CANDIDATE_TYPES[job.task_type]
        candidate_schema = {
            "candidate_type": (
                candidate_types[0]
                if len(candidate_types) == 1
                else " | ".join(candidate_types)
            ),
            "title": "string",
            "text": "string",
            "structured_payload": self._structured_payload_schema(job.task_type),
        }
        if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            candidate_schema["system_generated_evidence"] = (
                "Do not output claims or evidence. The system binds each mapping "
                "to the exact frozen field-profile evidence after validation."
            )
            candidate_schema["system_generated_mapping_provenance"] = (
                "Do not output mapping_provenance. The workbench injects exact "
                "per-field deterministic-rule or independent-AI origin metadata."
            )
        else:
            candidate_schema["claims"] = [
                {
                    "claim_id": "unique string",
                    "kind": ("fact | inference | recommendation | data_gap"),
                    "text": "string",
                    "confidence": "number from 0 to 1",
                    "uncertainty": "string",
                    "user_action": "string",
                    "evidence_ids": [
                        "authorized evidence ID from input_payload.evidence_packet"
                    ],
                }
            ]
            if (
                job.task_type
                != MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
            ):
                # Protocol jobs keep the evidence-binding instruction outside
                # the output schema so the pseudo-field can never consume the
                # single controlled repair opportunity.
                candidate_schema["system_generated_evidence"] = (
                    "Do not output evidence. Reference only evidence_id values from "
                    "input_payload.evidence_packet; the system materializes exact "
                    "source/hash/locator/content after validation."
                )
        output_schema = {
            "schema_version": MONITORING_AI_SCHEMA_VERSION,
            "task_id": job.job_id,
            "task_type": job.task_type.value,
            "input_revision_sha256": job.input_revision_sha256,
            "candidates": [candidate_schema],
        }
        if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            required_output_pairs = [
                f"{str(item['domain']).strip()}.{str(item['field']).strip()}"
                for item in provider_input_payload["field_profile"]["fields"]
            ]
            candidate_count = (
                "必须恰好输出1个listing_field_mapping_set候选，"
                "其中field_mappings必须且仅可完整覆盖input_payload.field_profile."
                "fields中的每个(domain,field)一次；不得输出任何未在该列表"
                "中出现的字段。本次唯一允许且必须输出的字段清单为："
                + "、".join(required_output_pairs)
                + "。"
            )
        elif job.task_type == MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES:
            candidate_count = "必须恰好输出2至3个候选。"
        elif job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
            candidate_count = (
                "输出1至3个彼此具有实质差异且均可编译的确定性规则模板候选；"
                "不得用标题或措辞变化伪装为不同候选。"
            )
        elif job.task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS:
            candidate_count = (
                "必须恰好输出2至3个彼此不重复的候选；每个候选必须引用"
                "至少两个真实原始数据域的证据。"
            )
        elif job.task_type in (
            MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            MonitoringAiTaskType.RISK_QUESTION_ANSWER,
        ):
            candidate_count = "必须恰好输出1个聚合候选。"
        else:
            candidate_count = "输出1至5个有实际价值且不重复的候选。"
        system_prompt = (
            "你是临床试验医学监查工作台中的独立产品AI。"
            "你只负责提出可追溯候选、证据、推断、不确定性和建议人工动作；"
            "不得改变正式风险状态、严重程度、处置结果或Query状态，"
            "不得声称内容已医学批准、待批准、无需复核或可直接外发；"
            "候选阶段统一使用“待用户确认”或“待医学复核”，用户采纳后即表示"
            "当前医学用户已确认该候选，不得再引入第二层医学批准状态。"
            "事实必须逐条绑定本次授权来源；推断和建议必须说明不确定性。"
            "如果证据不足，使用data_gap主张，不得补造数据、方案条款或医学事实。"
            "不得自行生成或改写证据对象、来源哈希和定位；只能引用输入"
            "evidence_packet中的evidence_id，系统会确定性绑定原始内容。"
            "面向用户的文字不得复述riskinst、monai、monrisk或monsrc等内部标识；"
            "以“当前风险”或“当前受试者”表述，工作台会确定性绑定实际对象。"
            "所有面向用户的标题、正文、不确定性和用户动作必须使用专业、简洁的中文；"
            "来源字段名、技术标识符和标准术语可保留原文。"
            "只返回一个严格符合output_schema的JSON对象，不要Markdown或额外说明。"
        )
        if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            system_prompt += (
                " 字段映射必须遵守scientific_boundary：EDC listing不是SDTM；"
                "CM只表示非试验用药/治疗，IP给药、剂量调整、停药、重启和"
                "依从性必须作为独立角色；标准仅能作为reference_only参照。"
                "field_kind必须按来源性质选择：source_collected为CRF/EDC直接"
                "采集值，source_metadata为OID、重复序号等系统元数据，"
                "standardized_coded仅用于具有源字段、编码体系及字典版本谱系的"
                "标准编码结果，deterministic_derived仅用于具有源字段和明确公式的"
                "确定性派生值，证据不足时使用unmapped。以双下划线开头的字段及"
                "DOMAIN属于来源技术元数据，必须标为source_metadata。画像中"
                "non_empty_count为0的全空字段缺少内容证据，必须标为unmapped，"
                "不得仅凭字段名赋予临床语义。不得仅凭字段边际频数声称"
                "术语与编码配对一致；必须依据relationships中的同一行配对指标。"
                "relationships只提供同域同行的聚合统计，不确认医学语义。"
                "site_identity_pair可用于判断中心编号与名称是否稳定配对，"
                "visit_identity_pair可用于判断访视显示名与OID/序号是否稳定配对，"
                "value_unit_pair可用于判断数值与单位是否同行出现，"
                "performed_reason_pair可用于判断执行标志与未执行原因的数据结构；"
                "这些关系不得被解释为中心主数据已确认、OID就是访视名称、"
                "单位已标准化或条件逻辑已由方案确认。"
                "分块任务中fields是本次必须且仅可输出映射的字段；"
                "domain_field_names仅用于核对同域血缘字段是否真实存在，不得为其中"
                "未出现在fields的字段输出映射。standardized_coded若缺少有效"
                "term_code_pair关系，必须降为source_collected或unmapped，"
                "不得臆测编码血缘。standardized_coded的source_fields必须包含"
                "同一行term_code_pair的另一侧字段，不得包含当前目标字段本身；"
                "coding_system必须是明确的编码体系，dictionary_version_field必须"
                "是真实独立的版本字段，不能把术语/文本字段冒充版本字段。"
                "若recommended_role声明为MedDRA、WHO Drug或其他标准编码体系的"
                "代码/标准术语角色，则不得标为普通source_collected：满足同行"
                "term_code_pair且domain_field_names中存在明确字典版本字段时，"
                "必须使用standardized_coded并给出完整血缘；证据不足时应改用不"
                "声称标准编码含义的来源角色或unmapped。当前字段"
                "画像不提供可重复计算的公式验证证据，因此独立AI不得输出"
                "deterministic_derived；无法证明时使用source_collected或unmapped。"
                "只有系统能够确定性识别的技术元数据字段已被排除；fields中仍可能"
                "包含尚未被确定性规则覆盖的技术元数据，这些字段仍必须逐一输出"
                "映射，不得因其看起来像技术字段而省略。required_output_field_names"
                "是本块唯一允许且必须逐一覆盖的输出清单。"
                "只输出剩余字段的语义映射，不要输出claims、evidence或"
                "mapping_provenance；系统会在校验后精确合并确定性映射，"
                "并把每项映射绑定到冻结字段画像和精确来源。"
                "read_only_domain_context中的representative_values和top_values"
                "是经过有界、脱敏处理的表单/页面实际值，可用于辨别背景治疗、"
                "试验药物给药或量表语境；它们只用于判断，绝不能作为"
                "field_mappings输出，也不得加入required_output_field_names。"
                " 域名或sheet名称不足以确定试验药物身份。即使来源域为EX或"
                "给药记录，也必须基于同域可引用证据（治疗身份字段、随机化"
                "治疗分配、IMP标志或方案/CRF给药身份）判断IP身份。无法确定"
                "身份时，保留来源值于中性treatment_administration角色下，"
                "标明身份未解决，不得直接赋为ip.administration角色。"
                "背景治疗、合并用药或抢救治疗不得提升为IP角色。"
                "每项治疗相关映射必须填写object_identity；同域身份依据必须"
                "逐字列入object_identity_evidence_fields。跨域随机化/治疗分配"
                "只能引用input_payload.field_profile.treatment_identity_bindings"
                "中与当前target_domain一致的binding_id，不得自行创造绑定。"
                " 计划剂量、处方剂量、实际给药剂量、发放量、回收量和派生"
                "剂量是互斥语义，必须分别映射。当同域多个剂量样字段证据"
                "不可区分或CRF标签缺失时，不得静默选择计划或实际剂量，"
                "应将dose_semantics设为unresolved并标明不确定性。"
                " 量表总分或评分不得仅因数值形状被归为程序编号或记录编号。"
                "必须综合表单/页面上下文、同胞条目、标签和值形状判断；"
                "来源总分保持source_collected。"
                " 当listing缺少独立识别剂量调整、暂停、恢复、永久停药及其他"
                "试验药物变更的字段族时，不得以缺少字段为依据声称未发生变更。"
                "应标明该能力不可用，而非推定无变更事件。"
            )
        elif (
            job.task_type
            == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ):
            system_prompt += (
                " 本任务的evidence_packet是结构化检索证据包，不代表已逐字"
                "核验整份方案。raw_fields.protocol_context.roles说明每条证据是"
                "关键词命中、同章节邻接、表格表头、同行条件/动作、列表标题"
                "还是列表条目。解释表格时必须把同一行的触发条件、阈值、"
                "复查时限、动作、例外和重启条件绑定为一个整体，不得只引用"
                "措施单元格。解释列表时必须保留列表标题与条目层级。"
                "在absence_assertion_authority为none时，绝对禁止写“方案未规定”、"
                "“方案未提供”或同义结论；只能写“当前证据包未检索到”，"
                "并将其标为检索缺口。"
                "context.detected_source_conflicts列出的每个冲突都必须在至少一个"
                "候选的source_conflicts中逐项原样返回全部conflict_id、action、"
                "modalities和evidence_ids，status固定为requires_user_resolution；"
                "正文、uncertainty和user_action必须说明需用户基于并列原文裁决，"
                "禁止按多数段落、常识或监管经验静默选择一种措辞。"
                "raw_fields.protocol_context.eligible_for_rule_fact为false的证据"
                "只能提供语境，不能独立支持规则事实；估计目标中的目标人群"
                "不等于入排资格人群。"
                "CM仅表示非试验用合并用药或治疗。试验药物给药、剂量调整、"
                "暂停、停药、重启、发放、回收和依从性必须归入独立IP语义，"
                "不得转写为CM规则，反之亦然。"
                " 输出中不得自行生成或改写证据对象、来源哈希和定位；"
                "只能引用input_payload.evidence_packet中的evidence_id，"
                "系统会在校验后确定性绑定原始内容。"
                " 每个候选 structured_payload 引用的不同 evidence_id（含"
                "source_conflicts 内的 evidence_ids）总计不得超过 "
                f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS} 个；"
                "证据引用应优先使用完整的表格同行/表头束；列表证据仅引用"
                "已选条目及其唯一上级标题，禁止枚举同级未选条目。"
            )
            context = input_payload.get("context")
            if (
                isinstance(context, dict)
                and context.get("topic_id") == "visit_window_and_order"
            ):
                system_prompt += (
                    " 本任务topic为访视时间窗与顺序(visit_window_and_order)。"
                    "每个访视候选只允许恰好一个访视动作家族：计划/时间窗、"
                    "改期/补访、计划外访视；改期/补访候选可以保留仅作为"
                    "标题、触发条件或动作对象的计划访视/访视窗口措辞，"
                    "但独立的计划/时间窗义务与改期/补访动作并存时必须"
                    "拆分为不同候选。访视候选禁止包含："
                    "试验药物或合并用药的给药/用药/应用/使用（含首次给药、"
                    "第1天给药、停用、暂停、恢复、剂量调整）、发放/回收/称重/"
                    "依从性/药代动力学、提前退出/失访/撤回（知情）同意、"
                    "安全性随访，以及不良事件或合并用药的收集/记录/询问。"
                    "“给药前7天内完成计划访视”是时间窗而非给药指令；"
                    "“末次给药后28天进行安全性随访”是安全性随访而非给药指令。"
                    " 以<时间窗/访视窗/研究日/允许范围/访视日>为/作为<参照|依据|基准>"
                    "的表述是对同一改期/补访动作的参照性补充，不是独立时间窗义务；"
                    "但独立的计划/时间窗义务、量化或规范性完成要求、数值窗口、"
                    "周/天和顺序断言与改期/补访动作并存时仍必须拆分为不同候选。"
                    " 原文仅表述“重新安排”时，不得扩展为原文未支持的“补访”；"
                    "必须保留原文措辞“原始访视日”，不得将其改写成窗口参照。"
                    " 受试者完成试验、试验结束/终止、试验开始/结束判定等完成/终止性"
                    "事实不属于访视时间窗与顺序主题：即使条款或标题提及“末次访视”"
                    "“计划访视”，也不得将其结构化为访视时间窗候选；真实末次访视时间窗"
                    "（如“末次访视应于第24周 D169±7d 完成”）仍按计划/时间窗候选结构化。"
                    " 被排除的原文内容不得通过委婉改写（如“相应环节”“研究相关操作”）"
                    "转写进访视候选：给药/发放/回收/退出/安全性随访/不良事件/合并用药等"
                    "被排除内容应整体省略，不得换词重述。"
                    " 禁止重复被排除主题/家族名称：任何用户可见字段（标题、正文、"
                    "subject_scope、conditions、time_windows、thresholds、"
                    "exceptions、required_actions、主张文本、uncertainty、"
                    "user_action）都不得仅为了说明某主题或动作家族被排除、省略"
                    "或未结构化而写出其名称（例如“不包含改期/补访、计划外访视”"
                    "“不结构化安全性随访”），不得写负向范围免责声明；"
                    "对被排除内容的指引必须保持通用且限于访视主题内部。"
                    " data_gap主张必须报告检索/证据/提问型不确定性（如“未检索到…”"
                    "“是否…”），其检索标记之前不得出现肯定性方案动作或义务；"
                    "FACT/INFERENCE/RECOMMENDATION主张保持可操作语义并接受"
                    "确定性校验，服务器校验是最终权威。"
                )
        elif job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
            system_prompt += (
                " 本任务输入中的fact_snapshot已经由当前医学经理明确选择，"
                "不是待批准内容；你不得修改、补充或推断新的方案事实。"
                "只可选择allowed_rule_families和allowed_fact_types中的值，"
                "且listing_mapping只能引用available_closed_roles中逐项列出的"
                "domain与source_field；字段角色键必须逐字使用该字段对应的"
                "rule_role，不得自造、缩写或绑定到其他语义角色。"
                "输出时每个字段绑定只写field和domain，"
                "不得生成lineage；系统会从当前不可变映射修订中注入可审计血缘。"
                "每个候选必须同时引用fact_evidence_id与mapping_evidence_id。"
                "CM只表示非试验用药或治疗；试验药物给药、剂量调整、暂停、恢复、"
                "停药、发放、回收和依从性必须使用独立IP域和角色。"
                "不得建议study_treatment_regimen等当前无安全确定性规则族的事实。"
                "工作台会在候选入库前使用真实确定性编译器预编译；不能编译的DSL"
                "将被拒绝并仅允许一次受控修复。"
            )
        return AiPromptEnvelope(
            task_id=job.job_id,
            task_type=AI_TASK_TYPE_BY_MONITORING_TASK[job.task_type],
            prompt_version=job.prompt_version,
            system_prompt=system_prompt,
            payload={
                "schema_version": MONITORING_AI_SCHEMA_VERSION,
                "monitoring_task_type": job.task_type.value,
                "task_contract": TASK_CONTRACTS[job.task_type],
                "candidate_types": list(candidate_types),
                "candidate_count_contract": candidate_count,
                "output_language": {
                    "human_readable_text": "zh-CN",
                    "recommended_role": "lower_snake_case technical role",
                    "source_fields": "copy source field names exactly",
                },
                "scientific_boundary": (
                    FIELD_MAPPING_SCIENTIFIC_BOUNDARY
                    if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    else None
                ),
                "field_kind_contract": (
                    {
                        "source_collected": (
                            "CRF/EDC直接采集或录入的来源值；不得提供derivation_lineage"
                        ),
                        "source_metadata": (
                            "EDC/ODM OID、重复序号或系统元数据；不得把OID值直接解释为"
                            "访视名称，不得提供derivation_lineage"
                        ),
                        "standardized_coded": (
                            "由来源字段经指定编码体系/词典形成的编码或标准术语；"
                            "必须提供不含目标字段自身的source_fields、明确coding_system、"
                            "独立dictionary_version_field，并有同一行term_code_pair"
                            "关系证据；版本字段不能是术语或文本字段"
                        ),
                        "deterministic_derived": (
                            "当前AI字段画像不含公式复算证明，不得由独立AI选择；"
                            "需人工确认后在字段映射草稿中另行设置"
                        ),
                        "unmapped": (
                            "证据不足、含义冲突或所需血缘缺失；说明缺口和确认动作"
                        ),
                    }
                    if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    else None
                ),
                "field_relationship_contract": (
                    {
                        "term_code_pair": (
                            "术语/代码同行聚合；标准化编码仍需明确编码体系、"
                            "独立字典版本字段和正确来源血缘"
                        ),
                        "site_identity_pair": (
                            "中心编号与名称同行聚合；不等于中心主数据已经确认"
                        ),
                        "visit_identity_pair": (
                            "访视显示名与OID/序号同行聚合；不得把OID直接翻译为访视名称"
                        ),
                        "value_unit_pair": (
                            "数值与单位字段同行聚合；不证明单位已标准化或完成换算"
                        ),
                        "performed_reason_pair": (
                            "是否执行标志与未执行原因同行聚合；不证明方案条件逻辑"
                        ),
                    }
                    if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    else None
                ),
                "project_id": job.project_id,
                "input_revision": job.input_revision.model_dump(mode="json"),
                "input_revision_sha256": job.input_revision_sha256,
                "input_payload_sha256": job.input_payload_sha256,
                "inference_payload_sha256": content_sha256(
                    provider_input_payload
                ),
                "input_payload": provider_input_payload,
                "authorized_source_pairs": [
                    {
                        "source_entry_id": item.source_entry_id,
                        "source_content_sha256": item.source_content_sha256,
                    }
                    for item in job.input_revision.sources
                ],
                "output_schema": output_schema,
            },
            reasoning_effort="high",
            max_output_tokens=(
                12_000
                if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                else 24_000
            ),
        )

    def _build_repair_envelope(
        self,
        job: MonitoringAiJob,
        input_payload: Dict[str, Any],
        invalid_output: Any,
        validation_errors: str,
        validation_diagnostics: Sequence[Dict[str, Any]] = (),
    ) -> AiPromptEnvelope:
        base = self._build_prompt_envelope(job, input_payload)
        deterministic_field_constraints: Optional[Dict[str, Any]] = None
        if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            fields = base.payload["input_payload"]["field_profile"]["fields"]
            deterministic_field_constraints = {
                "must_not_emit_fields_outside_inference_subset": True,
                "required_output_pairs": [
                    {
                        "domain": str(field["domain"]),
                        "source_field": str(field["field"]),
                    }
                    for field in fields
                ],
                "must_be_unmapped": [
                    {
                        "domain": str(field["domain"]),
                        "source_field": str(field["field"]),
                    }
                    for field in fields
                    if int(field.get("non_empty_count", 0)) == 0
                ],
                "instruction": (
                    "只重建required_output_pairs列出的本次AI字段子集；每项恰好"
                    "输出一次，不得输出任何其他字段。即使某字段看起来属于技术"
                    "元数据，只要出现在required_output_pairs中也必须输出。"
                    "全空的剩余业务字段必须保持unmapped。"
                ),
            }
        repair_payload = {
            "schema_version": MONITORING_AI_SCHEMA_VERSION,
            "output_schema": base.payload["output_schema"],
            "validation_errors": validation_errors,
            "invalid_output": invalid_output,
            "original_task": {
                "task_id": job.job_id,
                "monitoring_task_type": job.task_type.value,
                "task_contract": base.payload["task_contract"],
                "candidate_count_contract": base.payload[
                    "candidate_count_contract"
                ],
                "input_revision": base.payload["input_revision"],
                "input_revision_sha256": job.input_revision_sha256,
                "input_payload_sha256": job.input_payload_sha256,
                "input_payload": base.payload["input_payload"],
            },
            "authorized_source_pairs": base.payload["authorized_source_pairs"],
            "repair_contract": {
                "attempt": 1,
                "maximum_repairs": 1,
                "instruction": ("按原始任务和output_schema重建完整JSON对象。"),
            },
        }
        if validation_diagnostics:
            ordered_diagnostics = [
                dict(item) for item in validation_diagnostics
            ]
            affected_field_paths = list(
                dict.fromkeys(
                    str(item.get("field_path") or "").strip()
                    for item in ordered_diagnostics
                    if str(item.get("field_path") or "").strip()
                )
            )
            repair_payload["validation_diagnostics"] = ordered_diagnostics
            repair_payload["repair_contract"].update(
                {
                    "diagnostic_schema_version": (
                        _VISIT_TOPIC_DIAGNOSTIC_SCHEMA_VERSION
                    ),
                    "affected_field_paths": affected_field_paths,
                    "regenerate_complete_affected_fields": True,
                    "forbid_token_only_deletion": True,
                    "forbid_post_generation_mutation": True,
                    "instruction": (
                        "按原始任务和output_schema重建完整JSON对象。"
                        "对validation_diagnostics列出的每个field_path，"
                        "必须基于授权证据重新生成整个用户可见字段；不得只删除"
                        "matched_token、不得对模型输出做生成后文本替换，也不得"
                        "引入新来源或新事实。"
                    ),
                }
            )
        if deterministic_field_constraints is not None:
            repair_payload["deterministic_field_constraints"] = (
                deterministic_field_constraints
            )
        if job.task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING:
            context = input_payload.get("context")
            if (
                isinstance(context, dict)
                and context.get("evidence_packet_version")
                == PROTOCOL_EVIDENCE_PACKET_VERSION
            ):
                constraints = {
                    "max_evidence_ids_per_candidate": (
                        MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS
                    ),
                    "structure_bindings": (
                        "same-row condition/action cells with the available "
                        "table header; selected list items with their unique "
                        "ancestor title, no sibling enumeration; exact "
                        "conflict evidence sets"
                    ),
                    "instruction": (
                        "修复时只引用original_task.input_payload."
                        "evidence_packet中存在的evidence_id；每个候选引用的"
                        "不同evidence_id（含source_conflicts）不得超过 "
                        f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS} 个，"
                        "并保持表格同行/表头完整束；列表仅引用已选条目及其"
                        "唯一上级标题。"
                    ),
                }
                repair_context = input_payload.get("context")
                if (
                    isinstance(repair_context, dict)
                    and repair_context.get("topic_id")
                    == "visit_window_and_order"
                ):
                    constraints["visit_topic_constraints"] = (
                        "每个访视候选只允许恰好一个访视动作家族（计划/时间窗、"
                        "改期/补访、计划外访视）；改期/补访候选可以保留仅作为"
                        "标题、触发条件或动作对象的计划访视/访视窗口措辞，"
                        "但独立的计划/时间窗义务与改期/补访动作并存必须拆分"
                        "为不同候选；访视候选禁止包含给药/用药/应用/"
                        "使用（含首次给药）、发放/回收/称重/依从性/药代动力学、"
                        "退出/撤回（知情）同意、安全性随访、不良事件或合并用药"
                        "的收集/记录/询问。"
                        "以<时间窗/访视窗/研究日/允许范围/访视日>为/作为<参照|依据|基准>"
                        "是对同一改期/补访动作的参照性补充，不是独立时间窗义务；"
                        "独立的计划/时间窗义务、量化或规范性完成要求、数值窗口、"
                        "周/天和顺序断言与改期/补访动作并存必须拆分为不同候选。"
                        "修复必须保留原文措辞“原始访视日”，不得改写成窗口参照；"
                        "原文仅表述“重新安排”时，不得把“补访”扩展进标题或正文。"
                        "受试者完成试验、试验结束/终止、试验开始/结束判定等完成/终止性"
                        "事实必须整体省略或改述为检索缺口，不得以“末次访视”"
                        "“计划访视”为标题将其结构化。"
                        "被排除的原文内容不得通过委婉改写（如“相应环节”“研究相关操作”）"
                        "转写进访视候选，应整体省略。"
                        "任何用户可见字段（标题、正文、结构化字符串、主张文本、"
                        "uncertainty、user_action）不得仅为了说明被排除主题/"
                        "家族而重复其名称或写负向范围免责声明（例如“不包含改期/"
                        "补访、计划外访视”“不结构化安全性随访”）；修复必须删除"
                        "此类措辞，不得新增负向范围免责声明。"
                        "data_gap主张必须整体呈现检索/证据/提问型不确定性，"
                        "其检索标记之前不得出现肯定性方案动作或义务；"
                        "FACT/INFERENCE/RECOMMENDATION主张保持可操作语义。"
                    )
                repair_payload["protocol_evidence_constraints"] = constraints
        return AiPromptEnvelope(
            task_id=job.job_id,
            task_type=base.task_type,
            prompt_version=f"{job.prompt_version}:json-repair-1",
            system_prompt=(
                base.system_prompt
                + " 这是唯一一次JSON修复机会。只修复结构、枚举、证据绑定、"
                "候选数量和确定性措辞问题；不得引入任何新来源或新事实。"
            ),
            payload=repair_payload,
            reasoning_effort=base.reasoning_effort,
            max_output_tokens=base.max_output_tokens,
        )

    @staticmethod
    def _structured_payload_schema(
        task_type: MonitoringAiTaskType,
    ) -> Dict[str, Any]:
        if task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            return {
                "field_mappings": [
                    {
                        "domain": "source domain",
                        "source_field": "exact source field",
                        "recommended_role": "project-neutral monitoring role",
                        "field_kind": (
                            "source_collected | source_metadata | "
                            "standardized_coded | deterministic_derived | unmapped"
                        ),
                        "confidence": "number from 0 to 1",
                        "uncertainty": "missing information and uncertainty",
                        "user_action": "what the user should confirm",
                        "related_fields": ["related source field"],
                        "object_identity": (
                            "not_applicable | unresolved | "
                            "investigational_product | placebo | "
                            "active_comparator | background_therapy | "
                            "rescue_therapy | concomitant_non_ip | "
                            "other_non_ip_treatment"
                        ),
                        "object_identity_evidence_fields": [
                            "same-domain source field that establishes identity"
                        ],
                        "object_identity_binding_id": (
                            "exact authorized cross-domain binding_id or empty"
                        ),
                        "dose_semantics": (
                            "not_applicable | unresolved | planned | "
                            "prescribed | actual_administered | dispensed | "
                            "returned | duplicate_or_derived"
                        ),
                        "standards_reference": {
                            "reference_name": "CDASH | SDTM | terminology",
                            "reference_concept": "reference concept",
                            "reference_only": True,
                            "uncertainty": "reference limitations",
                        },
                        "derivation_lineage": (
                            "object or null; omit/null for source_collected, "
                            "source_metadata and unmapped. standardized_coded "
                            "requires source_fields, explicit coding_system and "
                            "an independent dictionary_version_field. "
                            "Do not emit deterministic_derived from this AI profile."
                        ),
                    }
                ]
            }
        if task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING:
            return {
                "clause_id": "string",
                "fact_type": (
                    "one allowed candidate_fact_types value from "
                    "input_payload.context.candidate_fact_types"
                ),
                "subject_scope": "string",
                "conditions": ["string"],
                "time_windows": ["string"],
                "thresholds": ["string"],
                "exceptions": ["string"],
                "required_actions": ["string"],
                "evidence_ids": [
                    "candidate evidence ID (at most "
                    f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS} distinct IDs per "
                    "candidate including source_conflicts evidence_ids)"
                ],
                "source_conflicts": [
                    {
                        "conflict_id": (
                            "exact conflict_id from "
                            "input_payload.context.detected_source_conflicts"
                        ),
                        "action": "exact conflicted action",
                        "modalities": [
                            "required | optional | prohibited"
                        ],
                        "status": "requires_user_resolution",
                        "evidence_ids": [
                            "all source evidence IDs for the conflict"
                        ],
                    }
                ],
            }
        if task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
            return {
                "fact_type": "one allowed fact type",
                "rule_family": "one allowed rule family",
                "rationale": "该模板如何忠实实现已确认事实",
                "tradeoffs": ["与其他候选的实质差异"],
                "deterministic_template": {
                    "template_version": "monitoring_rule_template_v2",
                    "rule_family": "same as rule_family",
                    "rule_key": "project-neutral stable key",
                    "executor": "field_predicate | cross_record | temporal",
                    "required_domains": ["source domain"],
                    "listing_mapping": {
                        "fields": {
                            "exact rule_role from available_closed_roles": {
                                "field": "exact available source field",
                                "domain": "exact available source domain",
                            }
                        }
                    },
                    "preconditions": "deterministic expression",
                    "trigger_expression": "deterministic expression",
                    "exclusions": "deterministic expression",
                    "title": "中文规则标题",
                    "severity": "low | medium | high | critical",
                    "evidence_template": "引用字段角色的中文证据模板",
                },
                "evidence_ids": [
                    "fact_evidence_id",
                    "mapping_evidence_id",
                ],
            }
        if task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS:
            return {
                "subject_id": "string",
                "domains": ["at least two domains"],
                "observations": ["string"],
                "temporal_relationships": ["string"],
                "data_gaps": ["string"],
                "recommended_review": "string",
                "evidence_ids": ["candidate evidence ID"],
            }
        if task_type == MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY:
            return {
                "risk_id": "string",
                "facts": ["string"],
                "inferences": ["string"],
                "data_gaps": ["string"],
                "recommended_actions": ["string"],
                "evidence_ids": ["candidate evidence ID"],
            }
        if task_type == MonitoringAiTaskType.RISK_QUESTION_ANSWER:
            return {
                "question": "string",
                "answer": "string",
                "evidence_limitations": ["string"],
                "follow_up_questions": ["string"],
                "evidence_ids": ["candidate evidence ID"],
            }
        return {
            "mode": "query | explanation",
            "observation": "string",
            "request_or_explanation": "string",
            "requested_follow_up": "string",
            "evidence_ids": ["candidate evidence ID"],
        }

    def _validate_task_specific_output(
        self,
        job: MonitoringAiJob,
        parsed: _ProviderOutput,
        input_payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], ...]:
        if (
            job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
            and len(parsed.candidates) != 1
        ):
            raise MonitoringAiOutputValidationError(
                "listing field mapping requires exactly one "
                "listing_field_mapping_set candidate"
            )
        if (
            job.task_type == MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES
            and not 2 <= len(parsed.candidates) <= 3
        ):
            raise MonitoringAiOutputValidationError(
                "Query/explanation task requires 2 to 3 candidates"
            )
        if (
            job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION
            and not 1 <= len(parsed.candidates) <= 3
        ):
            raise MonitoringAiOutputValidationError(
                "rule-template recommendation requires 1 to 3 candidates"
            )
        if (
            job.task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS
            and not 2 <= len(parsed.candidates) <= 3
        ):
            raise MonitoringAiOutputValidationError(
                "cross-table clue task requires 2 to 3 candidates"
            )
        if (
            job.task_type
            in (
                MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
                MonitoringAiTaskType.RISK_QUESTION_ANSWER,
            )
            and len(parsed.candidates) != 1
        ):
            raise MonitoringAiOutputValidationError(
                "risk summary and question-answer tasks require exactly one candidate"
            )
        normalized_titles = [
            re.sub(r"\s+", "", candidate.title).casefold()
            for candidate in parsed.candidates
        ]
        if len(normalized_titles) != len(set(normalized_titles)):
            raise MonitoringAiOutputValidationError(
                "monitoring AI candidates must have unique titles"
            )

        normalized_payloads: List[Dict[str, Any]] = []
        model_type = STRUCTURED_PAYLOAD_MODEL_BY_TASK[job.task_type]
        allowed_candidate_types = TASK_CANDIDATE_TYPES[job.task_type]
        is_protocol_task = (
            job.task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        )
        # Deterministic protocol failures are aggregated per candidate across
        # every candidate before the single controlled repair so the provider
        # sees one ordered response-level diagnostic with stable candidate
        # index/title. Prerequisite-stage failures (candidate type, forged
        # lineage, payload schema, structural repair, evidence materialization)
        # block only their own candidate's dependent checks; independent
        # candidates keep collecting.
        protocol_candidate_errors: List[Tuple[int, str, List[str]]] = []
        protocol_validation_diagnostics: List[Dict[str, Any]] = []

        def _candidate_error(
            candidate_state: Dict[str, Any],
            message: str,
            *,
            blocked: bool = False,
        ) -> None:
            if not is_protocol_task:
                raise MonitoringAiOutputValidationError(message)
            candidate_state["errors"].append(message)
            if blocked:
                candidate_state["blocked"] = True

        for candidate_index, candidate in enumerate(
            parsed.candidates,
            start=1,
        ):
            candidate_state: Dict[str, Any] = {
                "errors": [],
                "blocked": False,
                "diagnostics": [],
            }
            if candidate.candidate_type not in allowed_candidate_types:
                _candidate_error(
                    candidate_state,
                    "candidate_type does not match monitoring task; expected "
                    + " or ".join(allowed_candidate_types),
                    blocked=True,
                )
            if (
                not candidate_state["blocked"]
                and job.task_type
                == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
                and "repair_lineage" in candidate.structured_payload
            ):
                _candidate_error(
                    candidate_state,
                    "provider must not supply repair lineage fields",
                    blocked=True,
                )
            if not candidate_state["blocked"]:
                try:
                    structured = model_type.model_validate(
                        candidate.structured_payload
                    )
                except ValidationError as exc:
                    _candidate_error(
                        candidate_state,
                        self._controlled_validation_error_text(exc),
                        blocked=True,
                    )
                else:
                    if isinstance(structured, _QueryExplanationPayload):
                        expected_type = (
                            "query_candidate"
                            if structured.mode == "query"
                            else "explanation_candidate"
                        )
                        if candidate.candidate_type != expected_type:
                            raise MonitoringAiOutputValidationError(
                                "query/explanation candidate_type must match "
                                "payload mode"
                            )
                    normalized = structured.model_dump(
                        mode="json",
                        exclude_none=True,
                    )
            if (
                not candidate_state["blocked"]
                and job.task_type
                == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
            ):
                try:
                    normalized = self._repair_protocol_clause_evidence(
                        normalized,
                        input_payload,
                        candidate.claims,
                    )
                except MonitoringAiOutputValidationError as exc:
                    _candidate_error(
                        candidate_state,
                        str(exc),
                        blocked=True,
                    )
            if job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
                normalized = self._precompile_rule_template_recommendation(
                    normalized,
                    input_payload,
                )
            if (
                job.task_type
                == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS
                and input_payload.get("risk_instance_id")
            ):
                normalized["subject_id"] = "<current-subject>"
            if (
                job.task_type == MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY
                and input_payload.get("risk_instance_id")
            ):
                normalized["risk_id"] = str(input_payload["risk_instance_id"])
            if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
                raw_mappings = candidate.structured_payload.get(
                    "field_mappings",
                    [],
                )
                if any(
                    isinstance(mapping, dict)
                    and (
                        "validated_treatment_identity_binding" in mapping
                        or "quality_gate_actions" in mapping
                    )
                    for mapping in raw_mappings
                ):
                    raise MonitoringAiOutputValidationError(
                        "provider must not generate system quality-gate fields"
                    )
                if (
                    isinstance(structured, _ListingFieldMappingPayload)
                    and structured.mapping_provenance is not None
                ):
                    raise MonitoringAiOutputValidationError(
                        "provider must not generate mapping provenance"
                    )
                self._merge_deterministic_metadata_mappings(
                    normalized,
                    input_payload,
                )
                self._apply_field_mapping_post_quality_gate(
                    normalized,
                    input_payload,
                )
                self._materialize_field_profile_evidence(
                    job,
                    candidate,
                    normalized,
                    input_payload,
                )
                if not _contains_cjk(candidate.title) or any(
                    (
                        not _contains_cjk(
                            f"{mapping['uncertainty']}\n{mapping['user_action']}"
                        )
                        or (
                            mapping.get("standards_reference") is not None
                            and not _contains_cjk(
                                mapping["standards_reference"]["uncertainty"]
                            )
                        )
                    )
                    for mapping in normalized["field_mappings"]
                ):
                    raise MonitoringAiOutputValidationError(
                        "field mapping title, uncertainty, user_action and "
                        "standards_reference uncertainty must use "
                        "professional Chinese"
                    )
            elif (
                not candidate_state["blocked"] and candidate.evidence
            ):
                _candidate_error(
                    candidate_state,
                    "provider must not generate evidence objects",
                    blocked=True,
                )
            elif not candidate_state["blocked"]:
                try:
                    self._materialize_authorized_evidence(
                        candidate,
                        input_payload,
                    )
                except MonitoringAiOutputValidationError as exc:
                    _candidate_error(
                        candidate_state,
                        str(exc),
                        blocked=True,
                    )
            if not candidate_state["blocked"] and is_protocol_task:
                candidate_state["errors"].extend(
                    MonitoringAiService._validate_protocol_clause_candidate(
                        candidate,
                        normalized,
                        input_payload,
                    )
                )
                context = input_payload.get("context")
                if (
                    isinstance(context, dict)
                    and context.get("topic_id") == "visit_window_and_order"
                ):
                    candidate_state["diagnostics"].extend(
                        MonitoringAiService._visit_boundary_diagnostics(
                            candidate,
                            normalized,
                            candidate_index=candidate_index - 1,
                        )
                    )
            claims_or_evidence_missing = False
            if (
                not candidate_state["blocked"]
                and job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING
                and (not candidate.claims or not candidate.evidence)
            ):
                _candidate_error(
                    candidate_state,
                    "non-mapping candidates require claims and evidence",
                )
                claims_or_evidence_missing = True
            human_text = "\n".join(
                [
                    candidate.title,
                    candidate.text,
                    *[claim.text for claim in candidate.claims],
                    *[claim.uncertainty for claim in candidate.claims],
                    *[claim.user_action for claim in candidate.claims],
                ]
            )
            if (
                not candidate_state["blocked"]
                and _contains_internal_monitoring_identifier(human_text)
            ):
                _candidate_error(
                    candidate_state,
                    "user-facing monitoring text must not expose internal IDs",
                )
            if (
                not candidate_state["blocked"]
                and job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING
                and _contains_forbidden_sdtm_assertion(
                    "\n".join(
                        [
                            candidate.title,
                            candidate.text,
                            *[claim.text for claim in candidate.claims],
                            *[claim.user_action for claim in candidate.claims],
                        ]
                    )
                )
            ):
                _candidate_error(
                    candidate_state,
                    "EDC listing must not be asserted to be SDTM",
                )
            if not candidate_state["blocked"]:
                evidence_ids = {item.evidence_id for item in candidate.evidence}
                referenced_ids = self._structured_evidence_ids(
                    _ListingFieldMappingPayload.model_validate(normalized)
                    if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    else (
                        _ProtocolClausePayload.model_validate(normalized)
                        if job.task_type
                        == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
                        else structured
                    )
                )
                claim_referenced_ids = {
                    evidence_id
                    for claim in candidate.claims
                    for evidence_id in claim.evidence_ids
                }
                if not claims_or_evidence_missing:
                    if not referenced_ids.issubset(evidence_ids):
                        _candidate_error(
                            candidate_state,
                            "structured_payload references unknown candidate "
                            "evidence",
                        )
                    if not claim_referenced_ids.issubset(evidence_ids):
                        _candidate_error(
                            candidate_state,
                            "claim references unknown candidate evidence",
                        )
                if (
                    job.task_type
                    == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS
                ):
                    actual_domains = self._cross_table_source_domains(
                        candidate,
                        referenced_ids,
                    )
                    if len(actual_domains) < 2:
                        raise MonitoringAiOutputValidationError(
                            "each cross-table clue must cite original data "
                            "from at least two actual source domains"
                        )
                    normalized["domains"] = sorted(
                        actual_domains,
                        key=lambda value: (value.casefold(), value),
                    )
                if job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
                    used_evidence_ids = referenced_ids | claim_referenced_ids
                    candidate.evidence = [
                        item
                        for item in candidate.evidence
                        if item.evidence_id in used_evidence_ids
                    ]
            if not candidate_state["blocked"]:
                generated_payload_text = (
                    _field_mapping_assertion_text(normalized)
                    if job.task_type
                    == MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    else canonical_json(normalized)
                )
                if any(
                    phrase in generated_payload_text
                    for phrase in _FORBIDDEN_DEFINITIVE_PHRASES
                ):
                    _candidate_error(
                        candidate_state,
                        "structured_payload contains definitive approval "
                        "language",
                    )
                if _contains_forbidden_sdtm_assertion(generated_payload_text):
                    _candidate_error(
                        candidate_state,
                        "EDC listing must not be asserted to be SDTM",
                    )
                normalized_payloads.append(normalized)
            if candidate_state["errors"]:
                protocol_candidate_errors.append(
                    (
                        candidate_index,
                        candidate.title,
                        list(candidate_state["errors"]),
                    )
                )
                protocol_validation_diagnostics.extend(
                    candidate_state["diagnostics"]
                )

        if protocol_candidate_errors:
            detail = MonitoringAiService._bounded_protocol_candidate_errors(
                protocol_candidate_errors
            )
            raise MonitoringAiOutputValidationError(
                "protocol candidate validation failed:\n" + detail,
                diagnostics=protocol_validation_diagnostics,
            )

        if job.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            self._validate_field_mapping_coverage(
                normalized_payloads[0],
                input_payload,
                parsed.candidates[0],
            )
        if job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
            template_hashes = [
                content_sha256(item["deterministic_template"])
                for item in normalized_payloads
            ]
            if len(template_hashes) != len(set(template_hashes)):
                raise MonitoringAiOutputValidationError(
                    "rule-template candidates must have materially different DSL"
                )
        if (
            job.task_type
            == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ):
            self._validate_protocol_conflict_coverage(
                normalized_payloads,
                input_payload,
            )
        return tuple(normalized_payloads)

    @staticmethod
    def _repair_protocol_clause_evidence(
        normalized: Dict[str, Any],
        input_payload: Dict[str, Any],
        claims: Sequence[_ProviderClaim],
    ) -> Dict[str, Any]:
        """Apply deterministic typed structural-bundle repair.

        Runs after provider payload schema validation and before protocol
        clinical/structure validation. The repair covers every provider-
        selected semantic evidence ID: the structured payload evidence IDs,
        the exact conflict evidence sets and every claim evidence ID. Only
        exact same-row table cells with the available typed header path, or
        the unique ancestor title of an explicitly selected list item
        (grouped by its stable list bundle identity, never by
        ``parent_match_source_ids`` lineage), may be added from the same
        frozen packet. Conflict evidence sets stay unchanged and
        automatically added context never enters claim evidence IDs. The
        repair lineage is server-generated, typed and persisted inside the
        candidate structured payload; provider-forged lineage is rejected
        before normalization.
        """

        context = input_payload.get("context")
        evidence_packet = input_payload.get("evidence_packet")
        if (
            not isinstance(context, dict)
            or context.get("evidence_packet_version")
            != PROTOCOL_EVIDENCE_PACKET_VERSION
            or not isinstance(evidence_packet, (list, tuple))
        ):
            return normalized
        original: list[str] = []
        for evidence_id in normalized.get("evidence_ids") or ():
            cleaned = str(evidence_id).strip()
            if cleaned and cleaned not in original:
                original.append(cleaned)
        for conflict in normalized.get("source_conflicts") or ():
            for evidence_id in conflict.get("evidence_ids") or ():
                cleaned = str(evidence_id).strip()
                if cleaned and cleaned not in original:
                    original.append(cleaned)
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                cleaned = str(evidence_id).strip()
                if cleaned and cleaned not in original:
                    original.append(cleaned)
        try:
            result = repair_protocol_structural_bundles(
                original,
                evidence_packet,
            )
        except ProtocolStructuralRepairError as exc:
            raise MonitoringAiOutputValidationError(str(exc)) from exc
        normalized["evidence_ids"] = list(result.expanded_evidence_ids)
        normalized["repair_lineage"] = result.to_lineage()
        return normalized

    @staticmethod
    def _validate_protocol_clause_candidate(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
        input_payload: Dict[str, Any],
    ) -> List[str]:
        """Deterministic protocol candidate validation with ordered errors.

        Returns every deterministic validation failure for the candidate in
        documented order instead of raising on the first one, so the caller
        aggregates complete candidate-indexed diagnostics for the single
        controlled repair. Stable precedence: absence assertion, 50-ID cap,
        fact type, topic eligibility, direct IP/CM action misuse, visit-topic
        boundary (medication administration including first dose, dispensing/
        PK, withdrawal, safety follow-up, AE/CM collection, exactly one visit
        action family), unsupported makeup-visit term (补访 without a bound
        quote that directly supports it), structure bindings, claim anchors,
        declared conflicts. An empty list means the candidate passed every
        gate.
        """
        errors: List[str] = []
        context = input_payload.get("context")
        if not isinstance(context, dict):
            return errors
        if (
            context.get("evidence_packet_version")
            != "monitoring_protocol_evidence_packet_v3"
        ):
            return errors
        human_text = "\n".join(
            [
                candidate.title,
                candidate.text,
                canonical_json(normalized),
                *[claim.text for claim in candidate.claims],
                *[claim.uncertainty for claim in candidate.claims],
                *[claim.user_action for claim in candidate.claims],
            ]
        )
        if (
            context.get("absence_assertion_authority") != "full_document_verified"
            and MonitoringAiService._contains_unauthorized_protocol_absence_claim(
                human_text
            )
        ):
            errors.append(
                "bounded protocol evidence may only report a retrieval gap; "
                "it cannot assert that the protocol does not specify content"
            )

        evidence_by_id = {
            str(item.get("evidence_id") or "").strip(): item
            for item in input_payload.get("evidence_packet") or ()
            if isinstance(item, dict)
            and str(item.get("evidence_id") or "").strip()
        }
        used_ids = {
            str(item).strip()
            for item in normalized.get("evidence_ids") or ()
            if str(item).strip()
        }
        for conflict in normalized.get("source_conflicts") or ():
            used_ids.update(
                str(item).strip()
                for item in conflict.get("evidence_ids") or ()
                if str(item).strip()
            )
        for claim in candidate.claims:
            used_ids.update(
                str(item).strip()
                for item in claim.evidence_ids
                if str(item).strip()
            )
        if len(used_ids) > MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS:
            errors.append(
                "protocol candidate structured evidence IDs exceed "
                f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS}"
            )
        fact_type = str(normalized.get("fact_type") or "").strip()
        allowed_fact_types = {
            str(item).strip()
            for item in context.get("candidate_fact_types") or ()
            if str(item).strip()
        }
        if allowed_fact_types and fact_type not in allowed_fact_types:
            errors.append(
                "protocol candidate fact_type is not an allowed topic "
                "fact type"
            )
        topic_id = str(context.get("topic_id") or "").strip()
        if topic_id == "eligibility_continuity":
            eligible_ids = {
                evidence_id
                for evidence_id, evidence in evidence_by_id.items()
                if bool(
                    (
                        (evidence.get("raw_fields") or {}).get(
                            "protocol_context"
                        )
                        or {}
                    ).get("eligible_for_rule_fact", True)
                )
            }
            if not used_ids.intersection(eligible_ids):
                errors.append(
                    "estimand target-population context cannot independently "
                    "support an eligibility rule candidate"
                )

        action_scope_text = "\n".join(
            [
                str(normalized.get("subject_scope") or ""),
                *[
                    str(item)
                    for item in normalized.get("required_actions") or ()
                ],
            ]
        )
        if (
            topic_id == "concomitant_medication_policy"
            and _DIRECT_IP_CHANGE_RE.search(action_scope_text)
        ):
            errors.append(
                "CM protocol candidates cannot contain investigational-product "
                "dose, interruption, discontinuation or restart actions"
            )
        if (
            topic_id == "study_treatment"
            and _DIRECT_CM_CHANGE_RE.search(action_scope_text)
        ):
            errors.append(
                "investigational-product protocol candidates cannot use CM "
                "actions as study-treatment actions"
            )
        if topic_id == "visit_window_and_order":
            errors.extend(
                MonitoringAiService._visit_topic_errors(
                    MonitoringAiService._visit_boundary_view(
                        candidate,
                        normalized,
                    ),
                    MonitoringAiService._visit_topic_view(
                        candidate,
                        normalized,
                    ),
                    candidate,
                    normalized,
                )
            )
            errors.extend(
                MonitoringAiService._visit_unsupported_makeup_visit_errors(
                    MonitoringAiService._visit_topic_view(
                        candidate,
                        normalized,
                    ),
                    used_ids,
                    evidence_by_id,
                    conflict_evidence_ids={
                        str(item).strip()
                        for conflict in normalized.get("source_conflicts")
                        or ()
                        for item in conflict.get("evidence_ids") or ()
                        if str(item).strip()
                    },
                )
            )

        try:
            MonitoringAiService._validate_protocol_structure_bindings(
                used_ids,
                evidence_by_id,
            )
        except MonitoringAiOutputValidationError as exc:
            errors.append(str(exc))
        try:
            MonitoringAiService._validate_protocol_claim_anchors(
                candidate,
                evidence_by_id,
            )
        except MonitoringAiOutputValidationError as exc:
            errors.append(str(exc))
        try:
            MonitoringAiService._validate_declared_protocol_conflicts(
                candidate,
                normalized,
                context,
            )
        except MonitoringAiOutputValidationError as exc:
            errors.append(str(exc))
        return errors

    @staticmethod
    def _contains_unauthorized_protocol_absence_claim(text: str) -> bool:
        """Reject direct absence claims while allowing explicit negations.

        A sentence such as "不能断言方案未规定" preserves the retrieval-gap
        boundary; the embedded lexical phrase must not be mistaken for the
        prohibited affirmative claim.
        """

        for match in _UNAUTHORIZED_PROTOCOL_ABSENCE_RE.finditer(text):
            prefix = text[max(0, match.start() - 32) : match.start()]
            boundary = max(
                prefix.rfind("\n"),
                prefix.rfind("。"),
                prefix.rfind("；"),
                prefix.rfind("！"),
                prefix.rfind("？"),
            )
            clause_prefix = prefix[boundary + 1 :].strip()
            if _NEGATED_PROTOCOL_ABSENCE_PREFIX_RE.search(clause_prefix):
                continue
            return True
        return False

    @staticmethod
    def _visit_boundary_view(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
    ) -> str:
        """Full user-visible visit-topic text for topic-boundary gates.

        Covers every user-visible candidate surface: title/text, subject
        scope, conditions, time windows, thresholds, exceptions, required
        actions, claim text, claim uncertainty and user action. Mandated
        conflict pass-through text stays excluded; conflicts are validated
        for exact preservation and coverage separately.
        """

        return "\n".join(
            text
            for _field_path, text in (
                MonitoringAiService._visit_boundary_surfaces(
                    candidate,
                    normalized,
                )
            )
        )

    @staticmethod
    def _visit_boundary_surfaces(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
        *,
        candidate_index: Optional[int] = None,
    ) -> List[Tuple[str, str]]:
        """Ordered exact JSON field paths and full user-visible values.

        ``candidate_index`` is zero-based to match the provider output JSON.
        A one-based ``candidate_number`` is added to human-facing structured
        diagnostics separately. Keeping the surfaces structured prevents a
        family-level error from losing the exact field and token that must be
        regenerated during the single controlled repair.
        """

        prefix = (
            f"candidates[{candidate_index}]."
            if candidate_index is not None
            else ""
        )
        surfaces: List[Tuple[str, str]] = [
            (f"{prefix}title", candidate.title),
            (f"{prefix}text", candidate.text),
            (
                f"{prefix}structured_payload.subject_scope",
                str(normalized.get("subject_scope") or ""),
            ),
        ]
        for field_name in (
            "conditions",
            "time_windows",
            "thresholds",
            "exceptions",
            "required_actions",
        ):
            for index, item in enumerate(normalized.get(field_name) or ()):
                surfaces.append(
                    (
                        f"{prefix}structured_payload.{field_name}[{index}]",
                        str(item),
                    )
                )
        for index, claim in enumerate(candidate.claims):
            claim_prefix = f"{prefix}claims[{index}]"
            surfaces.extend(
                (
                    (f"{claim_prefix}.text", claim.text),
                    (f"{claim_prefix}.uncertainty", claim.uncertainty),
                    (f"{claim_prefix}.user_action", claim.user_action),
                )
            )
        return surfaces

    @staticmethod
    def _visit_boundary_diagnostics(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
        *,
        candidate_index: int,
    ) -> List[Dict[str, Any]]:
        """Return every forbidden-family hit with stable path and span.

        Ordering is candidate order, forbidden-family precedence, surface
        order, then regex match order. The exact span is included so repeated
        identical tokens in one field remain separately auditable while an
        exact duplicate emitted by overlapping validation plumbing is
        deterministically removed.
        """

        surfaces = MonitoringAiService._visit_boundary_surfaces(
            candidate,
            normalized,
            candidate_index=candidate_index,
        )
        diagnostics: List[Dict[str, Any]] = []
        seen: set[Tuple[Any, ...]] = set()
        for forbidden_family, regex in (
            _VISIT_TOPIC_FORBIDDEN_FAMILY_PATTERNS
        ):
            for field_path, text in surfaces:
                for match in regex.finditer(text):
                    matched_token = match.group(0)
                    key = (
                        candidate_index,
                        field_path,
                        forbidden_family,
                        match.start(),
                        match.end(),
                        matched_token,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    diagnostics.append(
                        {
                            "schema_version": (
                                _VISIT_TOPIC_DIAGNOSTIC_SCHEMA_VERSION
                            ),
                            "code": "visit_topic_forbidden_family",
                            "candidate_index": candidate_index,
                            "candidate_number": candidate_index + 1,
                            "field_path": field_path,
                            "matched_token": matched_token,
                            "match_start": match.start(),
                            "match_end": match.end(),
                            "forbidden_family": forbidden_family,
                            "repair_action": _VISIT_TOPIC_REPAIR_ACTION,
                        }
                    )
        return diagnostics

    @staticmethod
    def _visit_family_spans(text: str) -> List[Tuple[int, int]]:
        """Every visit-family detector span in position order."""

        spans: List[Tuple[int, int]] = []
        for regex in (
            _VISIT_RESCHEDULE_FAMILY_RE,
            _VISIT_RESCHEDULE_OBJECT_RE,
            _VISIT_UNSCHEDULED_FAMILY_RE,
            _VISIT_SCHEDULE_FAMILY_RE,
        ):
            spans.extend(
                (match.start(), match.end()) for match in regex.finditer(text)
            )
        return sorted(spans)

    @staticmethod
    def _visit_data_gap_is_retrieval(text: str) -> bool:
        """Whether a DATA_GAP claim text is excludable from family counting.

        Retrieval-scope dominance over family spans: within strong
        boundaries (。；！？ and newline) and adversative connectors
        (然而/但/同时), a retrieval, question or uncertainty marker governs
        family-bearing text only at or after that marker, so a later
        marker never retroactively washes an earlier affirmative family
        assertion (所有计划访视均应在时间窗内完成，当前证据包未检索到量化
        依据 stays fail-closed, with or without ；/但/然而/同时 joins). A
        retrieval scope established before the first family span propagates
        forward across coordination (且/并/而/、), so both
        当前证据包未检索到改期访视是否必须仍落在原访视窗内，并可超出原访视
        窗的适用条件 and the exact canary gap stay framed. Postpositive
        framing that would require reverse scope is fail-closed. A claim
        with no family-bearing span is vacuously framed.
        """

        for segment in _VISIT_DATA_GAP_SCOPE_BOUNDARY_RE.split(text):
            marker_starts = [
                match.start()
                for match in _VISIT_DATA_GAP_RETRIEVAL_FRAME_RE.finditer(
                    segment
                )
            ]
            for span_start, _span_end in MonitoringAiService._visit_family_spans(
                segment
            ):
                if not any(
                    marker_start <= span_start
                    for marker_start in marker_starts
                ):
                    return False
        return True

    @staticmethod
    def _visit_operative_surfaces(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
    ) -> List[Tuple[str, str]]:
        """Ordered (surface label, text) pairs of the operative visit view.

        Only content the provider chose as visit facts counts: candidate
        title/text, subject scope, conditions, time windows, thresholds,
        exceptions, required actions and claim text. Claim uncertainty and
        user action are review guidance, not protocol content, and cannot
        create a visit action family. Retrieval-framed DATA_GAP claim text
        is review guidance about missing evidence, not protocol content,
        and cannot create a visit action family either; it is excluded here
        while remaining in the full boundary view. Any other claim text -
        including a DATA_GAP claim that affirmatively states a protocol
        action or obligation without retrieval framing - stays operative,
        so family validation cannot be bypassed by changing claim kind.
        """

        surfaces: List[Tuple[str, str]] = [
            ("title", candidate.title),
            ("text", candidate.text),
            ("subject_scope", str(normalized.get("subject_scope") or "")),
        ]
        for field_name in (
            "conditions",
            "time_windows",
            "thresholds",
            "exceptions",
            "required_actions",
        ):
            for index, item in enumerate(normalized.get(field_name) or ()):
                surfaces.append((f"{field_name}[{index}]", str(item)))
        for index, claim in enumerate(candidate.claims):
            if (
                claim.kind == MonitoringAiClaimKind.DATA_GAP
                and MonitoringAiService._visit_data_gap_is_retrieval(
                    claim.text
                )
            ):
                continue
            surfaces.append(
                (f"claims[{index}].text (kind={claim.kind.value})", claim.text)
            )
        return surfaces

    @staticmethod
    def _visit_topic_view(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
    ) -> str:
        """Operative visit-topic text for the one-family classifier only.

        Only content the provider chose as visit facts counts: candidate
        title/text, subject scope, conditions, time windows, thresholds,
        exceptions, required actions and claim text. Claim uncertainty and
        user action are review guidance, not protocol content, and cannot
        create a visit action family. Retrieval-framed DATA_GAP claim text
        is also review guidance about missing evidence and cannot create a
        visit action family; it stays in the boundary view. Mandated
        conflict pass-through text is also excluded: conflicts are validated
        for exact preservation and coverage separately.
        """

        return "\n".join(
            text
            for _label, text in MonitoringAiService._visit_operative_surfaces(
                candidate,
                normalized,
            )
        )

    @staticmethod
    def _visit_family_names(family_text: str) -> List[str]:
        """Semantic-role aware visit action families in stable order.

        Reschedule and unscheduled families are lexical. The schedule family
        is role-aware: schedule/window wording used only as the title, the
        condition trigger, or the action object of a single reschedule rule
        does not create an independent schedule family. A segment with an
        independent normative or quantified schedule assertion, a week/day
        timing rule, or an equivalent remains schedule even when a separate
        reschedule segment exists.
        """

        families: List[str] = []
        if (
            _VISIT_RESCHEDULE_FAMILY_RE.search(family_text)
            or _VISIT_RESCHEDULE_OBJECT_RE.search(family_text)
        ):
            families.append("reschedule")
        if _VISIT_UNSCHEDULED_FAMILY_RE.search(family_text):
            families.append("unscheduled")
        if MonitoringAiService._visit_has_independent_schedule(family_text):
            families.append("schedule")
        return families

    @staticmethod
    def _visit_has_independent_schedule(family_text: str) -> bool:
        independent, _decisive_span = (
            MonitoringAiService._visit_schedule_independence(family_text)
        )
        return independent

    @staticmethod
    def _visit_schedule_independence(
        family_text: str,
    ) -> Tuple[bool, Optional[Tuple[int, int]]]:
        """Semantic schedule-role classification with the decisive span.

        Whether any operative segment carries an independent schedule
        assertion, plus the absolute (start, end) position of the exact
        schedule term whose independence decision triggered the
        classification, so the family trace can reuse the very span that
        validation relied on and can never diverge from it.

        Segments are the newline/；/。 separated parts of the operative
        family view, but action presence is evaluated over the complete
        operative candidate: structured output joins condition, time-window
        and required-action fields with newlines, so a trigger condition in
        one field can govern a reschedule action in the next field. A
        schedule match is not independent when it is the direct object of a
        reschedule verb (调整计划访视日期, 访视窗口改期, 计划访视补访), the
        timing/target constraint of a reschedule action (在访视窗口内重新
        安排, 调整...至访视窗口允许范围内), or the content of a conditional
        trigger clause (若/如果/无法/未能...) with an action elsewhere in
        the operative candidate. A normative modal (应/必须/需/须) proves an
        independent schedule obligation only when it is paired with a
        schedule predicate (完成/进行/参加/执行/随访/到访/记录/为/遵循/保持/
        遵守) on either side of the schedule term within the same comma/则
        clause; the modal must precede its predicate inside that clause, so
        a modal placed after the trigger phrase that governs the
        reschedule/unscheduled action (计划访视无法在窗口内完成时必须改期)
        does not pair with a trigger-phrase predicate such as 完成.
        进行/完成 are not schedule predicates when they directly
        govern 改期/补访/计划外访视. 所有/均 alone are subject quantifiers,
        while 所有/全部/各次访视...均/都 paired with a schedule predicate is
        an independent quantified schedule obligation. A schedule/window term
        directly defined by a numeric duration (访视窗口[规定]为±3天) is also
        self-sufficient even inside a trigger clause. The trigger
        protection also applies postpositively: a generic schedule/window
        term followed by a trigger marker (若/如果/一旦/无法/未能/不能/难以)
        inside the same clause (计划访视无法在窗口内完成时的改期/补访安排)
        is non-independent only while the candidate carries a real
        reschedule/unscheduled action and the clause holds no independent
        normative, quantified, numeric-window, week/day or ordering
        assertion. A plain nonnumeric schedule term inside a reference
        complement (以 <时间窗/访视窗/研究日/允许范围/访视日…> 为/作为
        <参照|依据|基准>, e.g. 以试验流程表规定的时间窗为原始参照) is a
        reschedule reference complement only while the candidate carries a
        real reschedule action (改期/重新安排/补访/调整访视日期 etc., never
        an unscheduled action alone) and the clause holds no quantified
        obligation. Reference complements that carry an independent numeric,
        week/day, D-day or ordering assertion (以第十二周的计划访视为参照,
        以D15的访视计划为参照, 以72小时的访视窗口为参照, 以3个工作日的访视
        窗口为参照, 以原定访视先后次序和访视安排为参照, 以第2周访视为参照,
        以访视顺序为参照) are detected by
        _VISIT_INDEPENDENT_SCHEDULE_REFERENCE_RE before the exemption and
        stay independent schedule content; the same holds for standalone
        ordering obligations such as 须遵循原定访视先后顺序. Without a real
        reschedule action the same reference wording remains an independent
        schedule assertion. A modal governing a reschedule action does not
        count. Global reschedule precedence is deliberately not implemented:
        a separate independent schedule segment still counts.
        """

        family_has_action = bool(
            _VISIT_RESCHEDULE_FAMILY_RE.search(family_text)
            or _VISIT_RESCHEDULE_OBJECT_RE.search(family_text)
            or _VISIT_UNSCHEDULED_FAMILY_RE.search(family_text)
        )
        # The reference-complement exemption is authorized only for a real
        # reschedule action; an unscheduled action alone never exempts a
        # schedule term inside 以…为参照.
        family_has_reschedule = bool(
            _VISIT_RESCHEDULE_FAMILY_RE.search(family_text)
            or _VISIT_RESCHEDULE_OBJECT_RE.search(family_text)
        )
        segment_offset = 0
        for segment in re.split(r"[；。\n]", family_text):
            object_spans = [
                (match.start(), match.end())
                for match in _VISIT_RESCHEDULE_OBJECT_RE.finditer(segment)
            ]
            target_spans = [
                (match.start(), match.end())
                for match in _VISIT_RESCHEDULE_TARGET_RE.finditer(segment)
            ]
            definition_spans = [
                (match.start(), match.end())
                for match in _VISIT_SCHEDULE_DEFINITION_RE.finditer(segment)
            ]
            reference_spans = [
                (match.start(), match.end())
                for match in _VISIT_SCHEDULE_REFERENCE_COMPLEMENT_RE.finditer(
                    segment
                )
            ]
            independent_reference_spans = [
                (match.start(), match.end())
                for match in _VISIT_INDEPENDENT_SCHEDULE_REFERENCE_RE.finditer(
                    segment
                )
            ]
            for match in _VISIT_SCHEDULE_FAMILY_RE.finditer(segment):
                decisive = (
                    segment_offset + match.start(),
                    segment_offset + match.end(),
                )
                if any(
                    start <= match.start() and match.end() <= end
                    for start, end in object_spans
                ):
                    continue
                if any(
                    start <= match.start() and match.end() <= end
                    for start, end in definition_spans
                ):
                    return True, decisive
                if any(
                    start <= match.start() and match.end() <= end
                    for start, end in independent_reference_spans
                ):
                    return True, decisive
                start = match.start()
                end = match.end()
                clause_start = max(
                    segment.rfind("，", 0, start),
                    segment.rfind("则", 0, start),
                ) + 1
                clause_ends = [
                    boundary
                    for boundary in (
                        segment.find("，", end),
                        segment.find("则", end),
                    )
                    if boundary != -1
                ]
                clause_end = (
                    min(clause_ends) if clause_ends else len(segment)
                )
                clause = segment[clause_start:clause_end]
                clause_prefix = segment[clause_start:start]
                if (
                    family_has_reschedule
                    and not _VISIT_QUANTIFIED_SCHEDULE_RE.search(clause)
                    and any(
                        start <= match.start() and match.end() <= end
                        for start, end in reference_spans
                    )
                ):
                    continue
                if _VISIT_NORMATIVE_SCHEDULE_RE.search(clause) and any(
                    modal.end() <= predicate.start()
                    for modal in _VISIT_NORMATIVE_SCHEDULE_RE.finditer(
                        clause
                    )
                    for predicate in _VISIT_SCHEDULE_PREDICATE_RE.finditer(
                        clause
                    )
                ):
                    return True, decisive
                if (
                    _VISIT_QUANTIFIED_SCHEDULE_RE.search(clause)
                    and _VISIT_SCHEDULE_PREDICATE_RE.search(clause)
                ):
                    return True, decisive
                if not family_has_action:
                    return True, decisive
                target_ok = False
                for span_start, span_end in target_spans:
                    if span_start <= start and end <= span_end:
                        if not _VISIT_SCHEDULE_PREDICATE_RE.search(
                            segment[
                                span_end : min(span_end + 14, clause_end)
                            ]
                        ):
                            target_ok = True
                            break
                if target_ok:
                    continue
                if _VISIT_TRIGGER_CLAUSE_RE.search(clause_prefix):
                    continue
                if (
                    family_has_action
                    and _VISIT_TRIGGER_CLAUSE_RE.search(
                        clause[len(clause_prefix):]
                    )
                    and not _VISIT_WEEKDAY_ORDERING_SCHEDULE_RE.search(
                        clause
                    )
                    and not _VISIT_SCHEDULE_DEFINITION_RE.search(clause)
                ):
                    continue
                return True, decisive
            segment_offset += len(segment) + 1
        return False, None

    @staticmethod
    def _family_locator_snippet(errors: List[str]) -> Optional[str]:
        """Return the first complete family locator in compact form."""

        family_error = next(
            (error for error in errors if "family trace:" in error),
            None,
        )
        if family_error is None:
            return None
        trace_start = family_error.find("family trace:") + len("family trace:")
        arrow = family_error.find(" <- ", trace_start)
        if arrow == -1:
            return None
        locator_start = family_error.rfind("; ", trace_start, arrow)
        locator_start = (
            trace_start if locator_start == -1 else locator_start + 2
        )
        locator_end = family_error.find("; ", arrow + 4)
        if locator_end == -1:
            locator_end = len(family_error)
        return "family trace: " + family_error[
            locator_start:locator_end
        ].strip()

    @staticmethod
    def _bounded_candidate_detail(
        errors: List[str],
        *,
        limit: int = _CANDIDATE_DIAGNOSTIC_LIMIT,
    ) -> str:
        """Bound one candidate diagnostic before response aggregation.

        If a family error exists, the bound is satisfied only when its first
        complete ``family <- locator`` survives; retaining the words
        ``family trace:`` alone is insufficient.
        """

        if limit <= 0:
            return ""
        detail = "; ".join(errors)
        if len(detail) <= limit:
            return detail
        bounded = detail[:limit]
        locator = MonitoringAiService._family_locator_snippet(errors)
        if locator is not None and locator not in bounded:
            if len(locator) + 4 > limit:
                return locator
            head_limit = max(0, limit - len(locator) - 4)
            return (
                bounded[:head_limit]
                + "... "
                + locator
            )
        return bounded

    @staticmethod
    def _bounded_protocol_candidate_errors(
        candidate_errors: List[Tuple[int, str, List[str]]],
    ) -> str:
        """Fit all candidate markers and one locator each below 4,000 chars.

        The downstream controlled-error wrapper adds the exception class and
        message prefix before applying its hard limit. Reserve those bytes
        first, preserve every legal full title, then allocate remaining
        diagnostic space left-to-right while reserving the minimum locator
        for every later candidate.
        """

        message_prefix = "protocol candidate validation failed:\n"
        exception_prefix = "MonitoringAiOutputValidationError: "
        budget = (
            _CONTROLLED_VALIDATION_ERROR_LIMIT
            - len(message_prefix)
            - len(exception_prefix)
        )
        markers = [
            f"candidate {index} ({title}): "
            for index, title, _errors in candidate_errors
        ]
        minimums = [
            MonitoringAiService._family_locator_snippet(errors)
            or "; ".join(errors)[:80]
            for _index, _title, errors in candidate_errors
        ]
        newline_budget = max(0, len(candidate_errors) - 1)
        mandatory = (
            sum(len(marker) for marker in markers)
            + sum(len(minimum) for minimum in minimums)
            + newline_budget
        )
        # Provider schema bounds (five 500-character titles) leave room for
        # the compact locators. Fail closed if future schema growth violates
        # that invariant instead of silently dropping a candidate marker.
        if mandatory > budget:
            raise MonitoringAiOutputValidationError(
                "protocol candidate diagnostics exceed controlled marker "
                "and locator budget"
            )

        remaining_extra = budget - mandatory
        lines: List[str] = []
        for position, (
            (index, title, errors),
            marker,
            minimum,
        ) in enumerate(zip(candidate_errors, markers, minimums)):
            candidates_left = len(candidate_errors) - position
            fair_extra = remaining_extra // candidates_left
            requested_limit = min(
                _CANDIDATE_DIAGNOSTIC_LIMIT,
                len(minimum) + fair_extra,
            )
            bounded = MonitoringAiService._bounded_candidate_detail(
                errors,
                limit=requested_limit,
            )
            lines.append(marker + bounded)
            remaining_extra -= max(0, len(bounded) - len(minimum))
        return "\n".join(lines)

    @staticmethod
    def _visit_family_trace(
        families: List[str],
        family_text: str,
        surfaces: List[Tuple[str, str]],
    ) -> List[str]:
        """One concise deterministic locator per detected family.

        Every locator is derived from the exact detectors and the exact
        semantic schedule classification that validation ran over the
        joined operative view, so the trace and the validation can never
        diverge: the reschedule/unscheduled locators are the first lexical
        detector matches, and the schedule locator is the decisive
        independent schedule span returned by
        ``_visit_schedule_independence`` (never a raw schedule token
        consumed by a reschedule object). The decisive span is mapped back
        to its operative surface label via cumulative offsets.
        """

        boundaries: List[Tuple[int, int, str]] = []
        cursor = 0
        for label, text in surfaces:
            boundaries.append((cursor, cursor + len(text), label))
            cursor += len(text) + 1

        def locator(span_start: int, span_end: int) -> str:
            for start, end, label in boundaries:
                if start <= span_start and span_end <= end:
                    span = family_text[span_start:span_end]
                    if len(span) > 60:
                        span = span[:60] + "…"
                    return f"{label} span {span!r}"
            return "operative view"

        trace: List[str] = []
        for family in families:
            if family == "reschedule":
                match = _VISIT_RESCHEDULE_FAMILY_RE.search(family_text)
                if match is None:
                    match = _VISIT_RESCHEDULE_OBJECT_RE.search(family_text)
                if match is not None:
                    trace.append(
                        f"{family} <- {locator(match.start(), match.end())}"
                    )
                else:
                    trace.append(f"{family} <- operative view")
            elif family == "unscheduled":
                match = _VISIT_UNSCHEDULED_FAMILY_RE.search(family_text)
                if match is not None:
                    trace.append(
                        f"{family} <- {locator(match.start(), match.end())}"
                    )
                else:
                    trace.append(f"{family} <- operative view")
            else:
                independent, decisive = (
                    MonitoringAiService._visit_schedule_independence(
                        family_text
                    )
                )
                if independent and decisive is not None:
                    trace.append(
                        f"{family} <- {locator(decisive[0], decisive[1])}"
                    )
                else:
                    trace.append(f"{family} <- operative view")
        return trace

    @staticmethod
    def _visit_topic_errors(
        boundary_text: str,
        family_text: str,
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
    ) -> List[str]:
        """Ordered visit-topic boundary and one-family atomicity failures.

        The topic-boundary gates (medication administration including first
        dose, dispensing/return/weighing/adherence/PK, early or consent
        withdrawal, safety follow-up, AE/CM collection, subject completion/
        study completion/end/start determination) scan the full
        user-visible boundary view, including claim uncertainty and user
        action. The exactly-one-family classifier scans only the operative
        family view. Precedence is documented and stable: medication,
        dispensing/PK, withdrawal, safety follow-up, AE/CM collection,
        study completion/end/start determination, then exactly-one-family.
        A genuine final-visit schedule such as 末次访视应于第24周 D169±7d
        完成 remains schedule content and is not a completion/end fact. The
        schedule family is semantic-role aware:
        schedule/window wording used only as a reschedule title, trigger or
        action object does not create a schedule family, while an
        independent schedule obligation plus a reschedule action still
        fails. Timing-only phrases such as 给药前7天内完成计划
        访视 are schedule/window references, not administration directives,
        and 末次给药后28天进行安全性随访 fails as safety follow-up, not as
        first-dose administration.
        """

        errors: List[str] = []
        if _VISIT_TOPIC_MEDICATION_ACTION_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain study-treatment "
                "or concomitant-medication actions"
            )
        if _VISIT_TOPIC_DISPENSING_PK_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain dispensing, "
                "return, weighing, adherence or PK content"
            )
        if _VISIT_TOPIC_WITHDRAWAL_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain early or consent "
                "withdrawal content"
            )
        if _VISIT_TOPIC_SAFETY_FOLLOWUP_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain safety follow-up "
                "content"
            )
        if _VISIT_TOPIC_COLLECTION_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain AE or CM "
                "collection content"
            )
        if _VISIT_TOPIC_STUDY_COMPLETION_RE.search(boundary_text):
            errors.append(
                "visit protocol candidates cannot contain subject "
                "completion, study completion/end or study start/end "
                "determination content"
            )
        surfaces = MonitoringAiService._visit_operative_surfaces(
            candidate,
            normalized,
        )
        families = MonitoringAiService._visit_family_names(family_text)
        # Fail-closed DATA_GAP kind-semantics rule: only retrieval-framed
        # DATA_GAP claim text is review guidance and can be excluded from
        # family counting. A DATA_GAP claim that affirmatively states a
        # visit action or obligation - in any clause, even when it adds no
        # new family relative to the rest of the candidate - always fails
        # the kind-semantics gate, so changing claim kind can never bypass
        # family validation.
        for index, claim in enumerate(candidate.claims):
            if claim.kind != MonitoringAiClaimKind.DATA_GAP:
                continue
            if MonitoringAiService._visit_data_gap_is_retrieval(
                claim.text
            ):
                continue
            claim_label = (
                f"claims[{index}].text (kind={claim.kind.value})"
            )
            errors.append(
                "visit DATA_GAP claim kind requires retrieval-gap "
                f"framing: {claim_label} carries affirmative visit "
                "action content; affirmative protocol actions or "
                "obligations cannot bypass family validation by "
                "changing claim kind"
            )
        if len(families) != 1:
            trace = MonitoringAiService._visit_family_trace(
                families,
                family_text,
                surfaces,
            )
            errors.append(
                "visit protocol candidate must contain exactly one visit "
                "action family; detected families: "
                + ", ".join(families)
                + "; family trace: "
                + "; ".join(trace)
            )
        return errors

    @staticmethod
    def _visit_unsupported_makeup_visit_errors(
        family_text: str,
        used_ids: set[str],
        evidence_by_id: Dict[str, Dict[str, Any]],
        conflict_evidence_ids: set[str] = frozenset(),
    ) -> List[str]:
        """Reject the exact makeup-visit action term 补访 without source
        support.

        补访 is a makeup-visit expansion of the reschedule family. When the
        operative visit candidate uses the exact term, at least one of its
        actually bound non-conflict evidence ids must carry a quote that
        directly contains 补访; otherwise the candidate expanded source
        wording such as 重新安排/改期 into an unsupported makeup-visit term
        and fails deterministically instead of relying on the prompt alone.
        Conflict-only evidence can never authorize the affirmative term:
        every normalized.source_conflicts[*].evidence_ids id is excluded
        from the support set even when a structural repair expanded it into
        normalized.evidence_ids.
        """

        if "补访" not in family_text:
            return []
        support_ids = used_ids.difference(conflict_evidence_ids)
        if any(
            evidence_id in evidence_by_id
            and "补访"
            in str(evidence_by_id[evidence_id].get("quote") or "")
            for evidence_id in support_ids
        ):
            return []
        return [
            "visit protocol candidate uses 补访 without a bound evidence "
            "quote that directly supports the makeup-visit term"
        ]

    @staticmethod
    def _validate_protocol_structure_bindings(
        used_ids: set[str],
        evidence_by_id: Dict[str, Dict[str, Any]],
    ) -> None:
        table_rows: dict[tuple[int, int], set[str]] = {}
        table_headers: dict[int, set[str]] = {}
        list_groups: dict[str, dict[str, set[str]]] = {}
        member_parent: dict[str, str] = {}
        list_member_ids: set[str] = set()
        for evidence_id, evidence in evidence_by_id.items():
            protocol_context = (
                (evidence.get("raw_fields") or {}).get("protocol_context")
                or {}
            )
            roles = set(protocol_context.get("roles") or ())
            structure = protocol_context.get("structure") or {}
            table_index = structure.get("table_index")
            row_index = structure.get("row_index")
            if (
                structure.get("kind") == "table_cell"
                and _is_non_bool_int(table_index)
                and _is_non_bool_int(row_index)
            ):
                table_rows.setdefault(
                    (table_index, row_index),
                    set(),
                ).add(evidence_id)
                if "table_header" in roles:
                    table_headers.setdefault(table_index, set()).add(
                        evidence_id
                    )
            if roles.intersection(("list_title", "list_item")):
                list_member_ids.add(evidence_id)
                bundle_id = str(
                    protocol_context.get("list_bundle_id") or ""
                ).strip()
                if not bundle_id:
                    # Missing stable bundle identity is not a typed list
                    # identity; used members are rejected below.
                    continue
                group = list_groups.setdefault(
                    bundle_id,
                    {"titles": set(), "items": set()},
                )
                if "list_title" in roles:
                    group["titles"].add(evidence_id)
                if "list_item" in roles:
                    group["items"].add(evidence_id)
                member_parent[evidence_id] = bundle_id

        used_table_cells = {
            evidence_id
            for evidence_id in used_ids
            if evidence_id in evidence_by_id
            and (
                (
                    evidence_by_id[evidence_id].get("raw_fields") or {}
                ).get("protocol_context")
                or {}
            ).get("structure", {}).get("kind")
            == "table_cell"
        }
        for evidence_id in used_table_cells:
            protocol_context = (
                (evidence_by_id[evidence_id].get("raw_fields") or {}).get(
                    "protocol_context"
                )
                or {}
            )
            structure = protocol_context.get("structure") or {}
            table_index = structure.get("table_index")
            row_index = structure.get("row_index")
            roles = set(protocol_context.get("roles") or ())
            if not (
                _is_non_bool_int(table_index)
                and _is_non_bool_int(row_index)
                and row_index >= 0
            ):
                raise MonitoringAiOutputValidationError(
                    "table clause evidence requires a typed table identity"
                )
            if row_index == 0 and "table_header" not in roles:
                raise MonitoringAiOutputValidationError(
                    "table clause evidence requires typed table headers"
                )
        untyped_list_ids = used_ids.intersection(
            list_member_ids.difference(member_parent)
        )
        if untyped_list_ids:
            raise MonitoringAiOutputValidationError(
                "list clause evidence requires a typed list identity"
            )
        used_data_rows = {
            (table_index, row_index)
            for (table_index, row_index), row_ids in table_rows.items()
            if row_index > 0 and row_ids.intersection(used_table_cells)
        }
        if used_table_cells and not used_data_rows:
            raise MonitoringAiOutputValidationError(
                "table clause evidence cannot select a row from header-only "
                "evidence"
            )
        if len({table_index for table_index, _row in used_data_rows}) > 1:
            raise MonitoringAiOutputValidationError(
                "table clause evidence cannot union cells across tables"
            )
        if len(used_data_rows) > 1:
            raise MonitoringAiOutputValidationError(
                "table clause evidence cannot union cells across rows"
            )
        for (table_index, row_index), row_ids in table_rows.items():
            row_used = used_table_cells.intersection(row_ids)
            if (
                row_index != 0
                and row_used
                and len(row_ids) >= 2
                and len(row_used) < 2
            ):
                raise MonitoringAiOutputValidationError(
                    "table clause evidence must bind the same-row condition "
                    "and action cells"
                )
            if (
                row_used
                and row_index != 0
                and table_headers.get(table_index)
                and not used_ids.intersection(table_headers[table_index])
            ):
                raise MonitoringAiOutputValidationError(
                    "table clause evidence must include the available table header"
                )

        used_list_ids = used_ids.intersection(member_parent)
        if used_list_ids:
            used_items = {
                evidence_id
                for evidence_id in used_list_ids
                if evidence_id
                in list_groups[member_parent[evidence_id]]["items"]
            }
            used_titles = {
                evidence_id
                for evidence_id in used_list_ids
                if evidence_id
                in list_groups[member_parent[evidence_id]]["titles"]
            }
            if len({member_parent[item_id] for item_id in used_items}) > 1:
                raise MonitoringAiOutputValidationError(
                    "list clause evidence cannot union entries across lists"
                )
            for item_id in used_items:
                titles = list_groups[member_parent[item_id]]["titles"]
                if len(titles) != 1:
                    raise MonitoringAiOutputValidationError(
                        "list clause evidence requires a unique list ancestor "
                        "title"
                    )
                title_id = next(iter(titles))
                if title_id not in used_ids:
                    raise MonitoringAiOutputValidationError(
                        "list clause evidence must bind the list ancestor "
                        "title"
                    )
            for title_id in used_titles:
                group = list_groups[member_parent[title_id]]
                if group["items"] and not used_items.intersection(
                    group["items"]
                ):
                    raise MonitoringAiOutputValidationError(
                        "list clause evidence must bind a selected entry from "
                        "the same list"
                    )

    @staticmethod
    def _validate_protocol_claim_anchors(
        candidate: _ProviderCandidate,
        evidence_by_id: Dict[str, Dict[str, Any]],
    ) -> None:
        """Require each claim to keep a provider-selected semantic anchor.

        Server-added structural context (headers, titles) is context-only and
        cannot make a claim pass: a claim that cites table structure must
        itself cite at least one non-header data-row cell, and a claim that
        cites list structure must itself cite at least one list item from
        each cited list. Untyped table/list identities fail closed. No text
        similarity or claim semantics are inferred.
        """

        for claim in candidate.claims:
            claim_ids = [
                str(item).strip()
                for item in claim.evidence_ids
                if str(item).strip()
            ]
            if not claim_ids:
                continue
            table_cited = False
            table_anchors: list[str] = []
            list_cited: dict[str, dict[str, set[str]]] = {}
            for evidence_id in claim_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    continue
                protocol_context = (
                    (evidence.get("raw_fields") or {}).get(
                        "protocol_context"
                    )
                    or {}
                )
                roles = set(protocol_context.get("roles") or ())
                structure = protocol_context.get("structure") or {}
                if structure.get("kind") == "table_cell":
                    table_index = structure.get("table_index")
                    row_index = structure.get("row_index")
                    if not (
                        _is_non_bool_int(table_index)
                        and _is_non_bool_int(row_index)
                        and row_index >= 0
                    ):
                        raise MonitoringAiOutputValidationError(
                            "claim table evidence requires a typed table "
                            "identity"
                        )
                    table_cited = True
                    if row_index > 0 and "table_header" not in roles:
                        table_anchors.append(evidence_id)
                if roles.intersection(("list_title", "list_item")):
                    bundle_id = str(
                        protocol_context.get("list_bundle_id") or ""
                    ).strip()
                    if not bundle_id:
                        raise MonitoringAiOutputValidationError(
                            "claim list evidence requires a typed list "
                            "identity"
                        )
                    group = list_cited.setdefault(
                        bundle_id,
                        {"titles": set(), "items": set()},
                    )
                    if "list_title" in roles:
                        group["titles"].add(evidence_id)
                    if "list_item" in roles:
                        group["items"].add(evidence_id)
            if table_cited and not table_anchors:
                raise MonitoringAiOutputValidationError(
                    "claim table evidence requires a provider-selected "
                    "data-row cell"
                )
            for group in list_cited.values():
                if not group["items"]:
                    raise MonitoringAiOutputValidationError(
                        "claim list evidence requires a provider-selected "
                        "entry from each cited list"
                    )

    @staticmethod
    def _validate_declared_protocol_conflicts(
        candidate: _ProviderCandidate,
        normalized: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        expected_by_id = {
            str(item.get("conflict_id") or "").strip(): item
            for item in context.get("detected_source_conflicts") or ()
            if isinstance(item, dict)
            and str(item.get("conflict_id") or "").strip()
        }
        for conflict in normalized.get("source_conflicts") or ():
            conflict_id = str(conflict.get("conflict_id") or "").strip()
            expected = expected_by_id.get(conflict_id)
            if expected is None:
                raise MonitoringAiOutputValidationError(
                    "protocol candidate declared an unknown source conflict"
                )
            if (
                str(conflict.get("action") or "") != expected.get("action")
                or set(conflict.get("modalities") or ())
                != set(expected.get("modalities") or ())
                or set(conflict.get("evidence_ids") or ())
                != set(expected.get("evidence_ids") or ())
            ):
                raise MonitoringAiOutputValidationError(
                    "protocol source conflict must preserve the exact action, "
                    "modalities and evidence set"
                )
            conflict_evidence = set(expected.get("evidence_ids") or ())
            if not any(
                claim.kind
                in (
                    MonitoringAiClaimKind.INFERENCE,
                    MonitoringAiClaimKind.DATA_GAP,
                )
                and conflict_evidence.issubset(set(claim.evidence_ids))
                and claim.uncertainty.strip()
                and claim.user_action.strip()
                for claim in candidate.claims
            ):
                raise MonitoringAiOutputValidationError(
                    "protocol source conflict requires an uncertainty claim "
                    "and explicit user-resolution action"
                )

    @staticmethod
    def _validate_protocol_conflict_coverage(
        normalized_payloads: Sequence[Dict[str, Any]],
        input_payload: Dict[str, Any],
    ) -> None:
        context = input_payload.get("context")
        if not isinstance(context, dict):
            return
        if (
            context.get("evidence_packet_version")
            != "monitoring_protocol_evidence_packet_v3"
        ):
            return
        expected = {
            str(item.get("conflict_id") or "").strip()
            for item in context.get("detected_source_conflicts") or ()
            if isinstance(item, dict)
            and str(item.get("conflict_id") or "").strip()
        }
        declared = {
            str(conflict.get("conflict_id") or "").strip()
            for payload in normalized_payloads
            for conflict in payload.get("source_conflicts") or ()
            if str(conflict.get("conflict_id") or "").strip()
        }
        if declared != expected:
            raise MonitoringAiOutputValidationError(
                "all detected protocol source conflicts must be preserved "
                "without omission or invention"
            )

    @staticmethod
    def _precompile_rule_template_recommendation(
        normalized: Dict[str, Any],
        input_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = input_payload.get("rule_template_context")
        if not isinstance(context, dict):
            raise MonitoringAiOutputValidationError(
                "rule-template context is missing"
            )
        fact_snapshot = context.get("fact_snapshot")
        mapping_snapshot = context.get("mapping_snapshot")
        available = context.get("available_closed_roles")
        if (
            not isinstance(fact_snapshot, dict)
            or not isinstance(mapping_snapshot, dict)
            or not isinstance(available, list)
        ):
            raise MonitoringAiOutputValidationError(
                "rule-template context is malformed"
            )
        allowed_fact_types = {
            str(item).strip()
            for item in context.get("allowed_fact_types") or ()
            if str(item).strip()
        }
        allowed_families = {
            str(item).strip()
            for item in context.get("allowed_rule_families") or ()
            if str(item).strip()
        }
        if normalized["fact_type"] not in allowed_fact_types:
            raise MonitoringAiOutputValidationError(
                "rule-template fact type is not allowed"
            )
        if normalized["rule_family"] not in allowed_families:
            raise MonitoringAiOutputValidationError(
                "rule-template family is not allowed"
            )
        template = deepcopy(normalized["deterministic_template"])
        if template.get("rule_family") != normalized["rule_family"]:
            raise MonitoringAiOutputValidationError(
                "rule-template family conflicts with its structured payload"
            )
        listing_mapping = template.get("listing_mapping")
        fields = (
            listing_mapping.get("fields")
            if isinstance(listing_mapping, dict)
            else None
        )
        if not isinstance(fields, dict) or not fields:
            raise MonitoringAiOutputValidationError(
                "rule-template listing mapping fields are required"
            )
        allowed_by_pair = {
            (
                str(item.get("domain") or "").strip().upper(),
                str(item.get("source_field") or "").strip(),
            ): item
            for item in available
            if isinstance(item, dict)
        }
        materialized_fields: Dict[str, Any] = {}
        for rule_role, raw_binding in fields.items():
            if not isinstance(raw_binding, dict) or set(raw_binding) != {
                "field",
                "domain",
            }:
                raise MonitoringAiOutputValidationError(
                    "AI rule-template field bindings may contain only field and domain"
                )
            pair = (
                str(raw_binding.get("domain") or "").strip().upper(),
                str(raw_binding.get("field") or "").strip(),
            )
            mapping_field = allowed_by_pair.get(pair)
            if mapping_field is None:
                raise MonitoringAiOutputValidationError(
                    "rule-template references a field outside the active closed mapping"
                )
            expected_rule_role = str(
                mapping_field.get("rule_role") or ""
            ).strip()
            if str(rule_role).strip() != expected_rule_role:
                raise MonitoringAiOutputValidationError(
                    "rule-template field role must exactly match the active "
                    "mapping rule_role"
                )
            materialized_fields[str(rule_role)] = {
                "field": pair[1],
                "domain": pair[0],
                "lineage": {
                    "source_type": "raw_listing_field",
                    "source_locator": str(
                        mapping_field.get("source_locator") or ""
                    ).strip(),
                },
            }
        template["listing_mapping"] = {
            "status": "medically_confirmed",
            "fields": materialized_fields,
        }
        required_evidence_ids = {
            str(context.get("fact_evidence_id") or "").strip(),
            str(context.get("mapping_evidence_id") or "").strip(),
        }
        if "" in required_evidence_ids or not required_evidence_ids.issubset(
            set(normalized["evidence_ids"])
        ):
            raise MonitoringAiOutputValidationError(
                "rule-template candidate must cite fact and mapping evidence"
            )
        temporary_fact = ProtocolFact.create(
            project_id=str(fact_snapshot["project_id"]),
            protocol_version_id=str(fact_snapshot["protocol_version_id"]),
            fact_key=str(fact_snapshot["fact_key"]),
            fact_type=str(fact_snapshot["fact_type"]),
            status="medically_confirmed",
            title=str(fact_snapshot["title"]),
            normalized_payload={TEMPLATE_PAYLOAD_KEY: template},
            source_entry_id=str(fact_snapshot["source_entry_id"]),
            source_locator=str(fact_snapshot["source_locator"]),
            source_text=str(fact_snapshot["source_text"]),
            applicability=fact_snapshot.get("applicability") or {},
        )
        try:
            compiled = compile_monitoring_rule_template(temporary_fact)
            for capability_id in required_capabilities_for_rule(compiled):
                require_monitoring_capability_snapshot(
                    mapping_snapshot.get("capability_states"),
                    capability_id,
                )
        except Exception as exc:
            raise MonitoringAiOutputValidationError(
                f"rule-template precompile failed: {exc}"
            ) from exc
        normalized["deterministic_template"] = template
        return normalized

    @staticmethod
    def _merge_deterministic_metadata_mappings(
        structured_payload: Dict[str, Any],
        input_payload: Dict[str, Any],
    ) -> None:
        profile_fields = input_payload["field_profile"]["fields"]
        deterministic_mappings = deterministic_metadata_mappings(profile_fields)
        deterministic_provenance = deterministic_metadata_provenance(profile_fields)
        deterministic_pairs = {
            (
                str(item["domain"]).strip(),
                str(item["source_field"]).strip(),
            )
            for item in deterministic_mappings
        }
        ai_mappings = list(structured_payload["field_mappings"])
        ai_pairs = [
            (
                str(item["domain"]).strip(),
                str(item["source_field"]).strip(),
            )
            for item in ai_mappings
        ]
        overlap = sorted(deterministic_pairs.intersection(ai_pairs))
        if overlap:
            rendered = ", ".join(f"{domain}.{field}" for domain, field in overlap)
            raise MonitoringAiOutputValidationError(
                "provider returned system-owned deterministic metadata fields: "
                + rendered
            )

        mappings_by_pair: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for mapping in [*deterministic_mappings, *ai_mappings]:
            pair = (
                str(mapping["domain"]).strip(),
                str(mapping["source_field"]).strip(),
            )
            mappings_by_pair.setdefault(pair, []).append(mapping)
        expected_pairs = [
            (
                str(field["domain"]).strip(),
                str(field["field"]).strip(),
            )
            for field in profile_fields
        ]
        ordered_mappings = [
            mapping
            for pair in expected_pairs
            for mapping in mappings_by_pair.pop(pair, [])
        ]
        ordered_mappings.extend(
            mapping
            for pair in sorted(mappings_by_pair)
            for mapping in mappings_by_pair[pair]
        )
        structured_payload["field_mappings"] = ordered_mappings

        deterministic_origin_by_pair = {
            (
                str(item["domain"]).strip(),
                str(item["source_field"]).strip(),
            ): item
            for item in deterministic_provenance
        }
        field_origins = []
        for mapping in ordered_mappings:
            pair = (
                str(mapping["domain"]).strip(),
                str(mapping["source_field"]).strip(),
            )
            deterministic_origin = deterministic_origin_by_pair.get(pair)
            field_origins.append(
                deterministic_origin
                if deterministic_origin is not None
                else {
                    "domain": pair[0],
                    "source_field": pair[1],
                    "origin": "independent_ai",
                    "rule_id": "",
                    "rule_version": "",
                    "rule_description": "",
                }
            )
        structured_payload["mapping_provenance"] = {
            "schema_version": "monitoring_field_mapping_provenance_v1",
            "assembled_by": "workbench_mapping_orchestrator",
            "field_origins": field_origins,
        }
        try:
            _ListingFieldMappingPayload.model_validate(structured_payload)
        except ValidationError as exc:
            raise MonitoringAiOutputValidationError(
                MonitoringAiService._controlled_validation_error_text(exc)
            ) from exc

    @staticmethod
    def _materialize_field_profile_evidence(
        job: MonitoringAiJob,
        candidate: _ProviderCandidate,
        structured_payload: Dict[str, Any],
        input_payload: Dict[str, Any],
    ) -> None:
        profile = input_payload["field_profile"]
        provenance = structured_payload["mapping_provenance"]
        origin_by_pair = {
            (
                str(item["domain"]).strip(),
                str(item["source_field"]).strip(),
            ): item
            for item in provenance["field_origins"]
        }
        has_ai_origin = any(
            item["origin"] == "independent_ai"
            for item in provenance["field_origins"]
        )
        if has_ai_origin:
            candidate.title = "字段映射建议"
            candidate.text = (
                "技术元数据由工作台确定性规则生成，其余字段由独立 AI "
                "提出候选；内容用于确认来源字段语义，不代表源 EDC "
                "listing 符合 SDTM。"
            )
        else:
            candidate.title = "技术元数据确定性映射"
            candidate.text = (
                "本组字段由工作台确定性技术规则生成，未调用独立 AI；"
                "规则只确认字段角色，不解释字段值的临床含义。"
            )
        profile_by_pair = {
            (
                str(item["domain"]).strip(),
                str(item["field"]).strip(),
            ): item
            for item in profile["fields"]
        }
        evidence: List[_ProviderEvidence] = []
        all_evidence_ids: List[str] = []
        profile_source = monitoring_field_profile_source_binding(
            profile["profile_sha256"]
        )
        for mapping in structured_payload["field_mappings"]:
            pair = (
                str(mapping["domain"]).strip(),
                str(mapping["source_field"]).strip(),
            )
            field_profile = profile_by_pair.get(pair)
            if field_profile is None:
                continue
            mapping_origin = origin_by_pair[pair]
            paired_relationships = [
                relationship
                for relationship in profile.get("relationships", [])
                if (
                    str(relationship.get("domain", "")).strip() == pair[0]
                    and pair[1]
                    in {
                        str(relationship.get("left_field", "")).strip(),
                        str(relationship.get("right_field", "")).strip(),
                    }
                )
            ]
            mapping_evidence_ids = []
            evidence_id = "profile_" + content_sha256(
                {
                    "input_revision_sha256": job.input_revision_sha256,
                    "profile_sha256": profile["profile_sha256"],
                    "domain": pair[0],
                    "field": pair[1],
                }
            )[:28]
            evidence.append(
                _ProviderEvidence(
                    evidence_id=evidence_id,
                    source_entry_id=profile_source.source_entry_id,
                    source_content_sha256=profile_source.source_content_sha256,
                    locator=(
                        f"field-profile://{profile['batch_id']}/"
                        f"{pair[0]}/{pair[1]}"
                    ),
                    raw_fields={
                        "domain": pair[0],
                        "field": pair[1],
                        "inferred_type": field_profile["inferred_type"],
                        "total_rows": field_profile["total_rows"],
                        "non_empty_count": field_profile["non_empty_count"],
                        "null_rate": field_profile["null_rate"],
                        "unique_value_count": field_profile[
                            "unique_value_count"
                        ],
                        "top_values": field_profile.get("top_values", []),
                        "representative_values": field_profile.get(
                            "representative_values",
                            [],
                        ),
                        "anomaly_examples": field_profile.get(
                            "anomaly_examples",
                            [],
                        ),
                        "paired_relationships": paired_relationships,
                        "profile_sha256": profile["profile_sha256"],
                        "payload_policy": profile.get("payload_policy", ""),
                        "source_lineage": profile["source_bindings"],
                        "mapping_origin": mapping_origin["origin"],
                        "deterministic_rule_id": mapping_origin.get("rule_id", ""),
                        "deterministic_rule_version": mapping_origin.get(
                            "rule_version",
                            "",
                        ),
                        "deterministic_rule_description": mapping_origin.get(
                            "rule_description",
                            "",
                        ),
                        "ai_inference_used": (
                            mapping_origin["origin"] == "independent_ai"
                        ),
                    },
                )
            )
            mapping_evidence_ids.append(evidence_id)
            all_evidence_ids.append(evidence_id)
            mapping["evidence_ids"] = mapping_evidence_ids
        candidate.evidence = evidence
        candidate.claims = [
            _ProviderClaim(
                claim_id=f"profile-mapping-{index // 20 + 1}",
                kind=(
                    MonitoringAiClaimKind.RECOMMENDATION
                    if has_ai_origin
                    else MonitoringAiClaimKind.FACT
                ),
                text=(
                    "建议按冻结字段画像审阅本组字段语义映射。"
                    if has_ai_origin
                    else "本组技术字段由工作台确定性规则映射，未调用独立 AI。"
                ),
                confidence=0.8 if has_ai_origin else 1.0,
                uncertainty=(
                    "字段画像不能替代项目数据字典和医学经理确认。"
                    if has_ai_origin
                    else "规则不解释技术标识值的具体临床含义。"
                ),
                user_action=(
                    "确认或修订字段角色后再形成正式映射。"
                    if has_ai_origin
                    else "如项目数据字典定义不同，请在映射草稿中修订。"
                ),
                evidence_ids=all_evidence_ids[index : index + 20],
            )
            for index in range(0, len(all_evidence_ids), 20)
        ]

    @staticmethod
    def _materialize_authorized_evidence(
        candidate: _ProviderCandidate,
        input_payload: Dict[str, Any],
    ) -> None:
        candidate.evidence = [
            _ProviderEvidence.model_validate(item)
            for item in input_payload["evidence_packet"]
        ]

    @staticmethod
    def _structured_evidence_ids(structured: BaseModel) -> set[str]:
        if isinstance(structured, _ListingFieldMappingPayload):
            return {
                evidence_id
                for mapping in structured.field_mappings
                for evidence_id in mapping.evidence_ids
            }
        if isinstance(structured, _ProtocolClausePayload):
            return set(structured.evidence_ids).union(
                evidence_id
                for conflict in structured.source_conflicts
                for evidence_id in conflict.evidence_ids
            )
        return set(getattr(structured, "evidence_ids"))

    @staticmethod
    def _cross_table_source_domains(
        candidate: _ProviderCandidate,
        referenced_ids: set[str],
    ) -> set[str]:
        domains: set[str] = set()
        for evidence in candidate.evidence:
            if evidence.evidence_id not in referenced_ids:
                continue
            raw_fields = evidence.raw_fields
            if raw_fields.get("evidence_kind") != "original_data":
                continue
            direct_domain = str(raw_fields.get("domain", "")).strip()
            if direct_domain:
                domains.add(direct_domain)
            fields = raw_fields.get("fields")
            if isinstance(fields, list):
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    if str(field.get("field", "")).strip().upper() != "DOMAIN":
                        continue
                    value = str(field.get("value", "")).strip()
                    if value and not value.startswith("<"):
                        domains.add(value)
            locator = str(evidence.locator).strip()
            match = re.search(r"(?:^|:)sheet:([^:/]+)", locator, re.IGNORECASE)
            if match:
                domains.add(match.group(1).strip())
        return {domain for domain in domains if domain}

    @staticmethod
    def _apply_field_mapping_post_quality_gate(
        structured_payload: Dict[str, Any],
        input_payload: Dict[str, Any],
    ) -> None:
        """Conservatively normalize treatment identity and dose ambiguity.

        The provider may propose semantics, but IP identity is accepted only
        when the frozen profile supplies same-domain evidence or an explicit
        cross-domain binding. Domain names never act as identity evidence.
        """

        profile = input_payload["field_profile"]
        profile_fields = [
            item for item in profile.get("fields", []) if isinstance(item, dict)
        ]
        context_profile_fields = [
            item
            for item in profile.get(
                "read_only_domain_context_profiles",
                [],
            )
            if isinstance(item, dict)
        ]
        profile_pairs = {
            (
                str(item.get("domain", "")).strip(),
                str(item.get("field", "")).strip(),
            )
            for item in profile_fields
        }
        profile_pairs.update(
            (
                str(item.get("domain", "")).strip(),
                str(item.get("field", "")).strip(),
            )
            for item in context_profile_fields
        )
        profile_pairs.update(
            (
                str(item.get("domain", "")).strip(),
                str(item.get("field", "")).strip(),
            )
            for item in profile.get(
                "treatment_identity_binding_source_pairs",
                [],
            )
            if isinstance(item, dict)
        )
        context_by_domain: Dict[str, str] = {}
        for field in [*profile_fields, *context_profile_fields]:
            domain = str(field.get("domain", "")).strip()
            fragments: List[str] = [str(field.get("field", "")).strip()]
            for value in field.get("representative_values", [])[:5]:
                fragments.append(str(_bounded_context_value(value)))
            for item in field.get("top_values", [])[:5]:
                if isinstance(item, dict):
                    fragments.append(
                        str(_bounded_context_value(item.get("value")))
                    )
            field_context = " ".join(fragments).casefold()
            context_by_domain[domain.casefold()] = " ".join(
                (
                    context_by_domain.get(domain.casefold(), ""),
                    field_context,
                )
            ).casefold()

        bindings: Dict[str, _TreatmentIdentityBinding] = {}
        for raw_binding in profile.get("treatment_identity_bindings", []):
            binding = _TreatmentIdentityBinding.model_validate(raw_binding)
            bindings[binding.binding_id] = binding

        mappings = structured_payload.get("field_mappings", [])
        mapping_pairs = {
            (
                str(item.get("domain", "")).strip(),
                str(item.get("source_field", "")).strip(),
            )
            for item in mappings
            if isinstance(item, dict)
        }
        same_domain_identity: set[str] = set()
        domain_non_ip_identity: Dict[str, str] = {}
        for mapping in mappings:
            domain = str(mapping.get("domain", "")).strip()
            domain_key = domain.casefold()
            identity = str(
                mapping.get("object_identity", "not_applicable")
            ).strip()
            evidence_fields = {
                str(value).strip()
                for value in mapping.get(
                    "object_identity_evidence_fields",
                    [],
                )
                if str(value).strip()
            }
            valid_evidence = bool(evidence_fields) and all(
                (domain, source_field) in profile_pairs
                or (domain, source_field) in mapping_pairs
                for source_field in evidence_fields
            )
            # A provider-assigned IP identity, even with self-consistent
            # cited evidence, is circular self-attestation and never
            # anchors a domain here; independent anchors are the frozen
            # source context markers below and validated identity bindings.
            if identity in _NON_IP_OBJECT_IDENTITIES and valid_evidence:
                domain_non_ip_identity[domain_key] = identity

        for domain_key, context in context_by_domain.items():
            for identity, markers in _NON_IP_CONTEXT_MARKERS.items():
                if any(marker.casefold() in context for marker in markers):
                    domain_non_ip_identity[domain_key] = identity
                    break
            if any(marker.casefold() in context for marker in _IP_CONTEXT_MARKERS):
                same_domain_identity.add(domain_key)

        for mapping in mappings:
            domain = str(mapping.get("domain", "")).strip()
            domain_key = domain.casefold()
            role = str(mapping.get("recommended_role", "")).strip()
            role_key = re.sub(r"[\s_:/\\-]+", ".", role.casefold())
            binding_id = str(
                mapping.get("object_identity_binding_id", "")
            ).strip()
            binding = bindings.get(binding_id)
            binding_valid = bool(
                binding is not None
                and binding.target_domain.casefold() == domain_key
                and (
                    binding.source_domain,
                    binding.source_field,
                )
                in profile_pairs
            )
            if binding_valid and binding is not None:
                mapping["validated_treatment_identity_binding"] = (
                    binding.model_dump(mode="json")
                )
            elif binding_id:
                mapping["object_identity_binding_id"] = ""
                mapping["validated_treatment_identity_binding"] = None
                _append_mapping_quality_note(
                    mapping,
                    action_code="invalid_treatment_identity_binding",
                    uncertainty=(
                        "所引用的跨域治疗身份绑定未在冻结字段画像中通过校验。"
                    ),
                    user_action=(
                        "请确认随机分组或治疗分配来源与当前给药域的受试者级"
                        "连接关系。"
                    ),
                )

            non_ip_identity = domain_non_ip_identity.get(domain_key)
            is_cm_domain = domain_key == "cm"
            is_ip_role = role_key.startswith("ip.")
            is_treatment_role = role_key.startswith(
                "treatment.administration"
            )
            if not (is_ip_role or is_treatment_role):
                continue

            if non_ip_identity or is_cm_domain:
                identity = (
                    non_ip_identity
                    or "concomitant_non_ip"
                )
                mapping["object_identity"] = identity
                mapping["recommended_role"] = (
                    "cm.source_other"
                    if is_cm_domain
                    else "treatment.administration.neutral"
                )
                mapping["dose_semantics"] = (
                    "unresolved"
                    if _mapping_is_dose_like(mapping)
                    else "not_applicable"
                )
                mapping["confidence"] = min(
                    float(mapping.get("confidence", 0.0)),
                    0.55,
                )
                _append_mapping_quality_note(
                    mapping,
                    action_code="non_ip_treatment_neutralized",
                    uncertainty=(
                        "来源表单或同行内容指向背景、救援或合并治疗，"
                        "不能按试验药物解释。"
                    ),
                    user_action=(
                        "请核对治疗身份；如确为试验药物，需补充同域身份字段"
                        "或经审计的跨域治疗分配绑定。"
                    ),
                )
                continue

            identity_anchored = (
                domain_key in same_domain_identity or binding_valid
            )
            if not identity_anchored:
                mapping["object_identity"] = "unresolved"
                mapping["confidence"] = min(
                    float(mapping.get("confidence", 0.0)),
                    0.55,
                )
                if role_key.startswith(("ip.administration", "ip.dose.")):
                    mapping["recommended_role"] = (
                        "treatment.administration.neutral"
                    )
                if _mapping_is_dose_like(mapping):
                    mapping["dose_semantics"] = "unresolved"
                _append_mapping_quality_note(
                    mapping,
                    action_code="treatment_identity_unresolved",
                    uncertainty=(
                        "当前域缺少可审计的试验药物、安慰剂或阳性对照"
                        "身份证据。"
                    ),
                    user_action=(
                        "请确认同域治疗名称/角色/IMP字段，或建立受试者级"
                        "随机治疗分配到当前给药域的显式绑定。"
                    ),
                )

        MonitoringAiService._normalize_ambiguous_dose_mappings(
            mappings,
            profile_fields,
        )
        MonitoringAiService._normalize_scale_total_mappings(
            mappings,
            profile,
            context_by_domain,
        )

    @staticmethod
    def _normalize_scale_total_mappings(
        mappings: List[Dict[str, Any]],
        profile: Dict[str, Any],
        context_by_domain: Dict[str, str],
    ) -> None:
        """Close source scale totals without claiming workbench recalculation."""

        domain_field_names = {
            str(field).strip()
            for field in profile.get("domain_field_names", [])
            if str(field).strip()
        }
        domain_field_names.update(
            str(item.get("field", "")).strip()
            for item in [
                *profile.get("fields", []),
                *profile.get("read_only_domain_context_profiles", []),
            ]
            if isinstance(item, dict) and str(item.get("field", "")).strip()
        )
        for mapping in mappings:
            domain = str(mapping.get("domain", "")).strip()
            source_field = str(mapping.get("source_field", "")).strip()
            match = re.fullmatch(
                r"(?P<stem>[A-Za-z][A-Za-z0-9_]{1,80}?)(?:NUM|TOTAL|SCORE|SUM)",
                source_field,
                flags=re.IGNORECASE,
            )
            if match is None:
                continue
            stem = match.group("stem")
            sibling_pattern = re.compile(
                rf"^{re.escape(stem)}\d+$",
                flags=re.IGNORECASE,
            )
            item_fields = sorted(
                field
                for field in domain_field_names
                if sibling_pattern.fullmatch(field)
            )
            domain_context = context_by_domain.get(domain.casefold(), "")
            if len(item_fields) < 2 or not any(
                marker.casefold() in domain_context
                for marker in _SCALE_CONTEXT_MARKERS
            ):
                continue

            mapping["recommended_role"] = "scale.total_score"
            mapping["field_kind"] = MonitoringFieldKind.SOURCE_COLLECTED.value
            mapping["derivation_lineage"] = None
            mapping["object_identity"] = "not_applicable"
            mapping["object_identity_evidence_fields"] = []
            mapping["object_identity_binding_id"] = ""
            mapping["validated_treatment_identity_binding"] = None
            mapping["dose_semantics"] = "not_applicable"
            mapping["related_fields"] = sorted(
                {
                    *[
                        str(value).strip()
                        for value in mapping.get("related_fields", [])
                        if str(value).strip()
                    ],
                    *item_fields,
                }
            )
            mapping["confidence"] = min(
                float(mapping.get("confidence", 0.0)),
                0.85,
            )
            _append_mapping_quality_note(
                mapping,
                action_code="scale_source_total_closed",
                uncertainty=(
                    "该字段按同域量表语境和同前缀条目字段保留为来源采集总分；"
                    "当前未绑定量表版本、分支、缺失计分规则或复算公式。"
                ),
                user_action=(
                    "可展示来源总分；启用工作台复算前需确认正式量表版本和"
                    "完整计分规则。"
                ),
            )

    @staticmethod
    def _normalize_ambiguous_dose_mappings(
        mappings: List[Dict[str, Any]],
        profile_fields: List[Dict[str, Any]],
    ) -> None:
        profile_by_pair = {
            (
                str(item.get("domain", "")).strip(),
                str(item.get("field", "")).strip(),
            ): item
            for item in profile_fields
        }
        by_signature: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for mapping in mappings:
            if not _mapping_is_dose_like(mapping):
                continue
            pair = (
                str(mapping.get("domain", "")).strip(),
                str(mapping.get("source_field", "")).strip(),
            )
            profile = profile_by_pair.get(pair, {})
            signature_payload = {
                "top_values": profile.get("top_values", []),
                "representative_values": profile.get(
                    "representative_values",
                    [],
                ),
                "inferred_type": profile.get("inferred_type"),
            }
            signature = content_sha256(signature_payload)
            by_signature.setdefault((pair[0].casefold(), signature), []).append(
                mapping
            )

        ambiguous: set[int] = set()
        for same_signature in by_signature.values():
            if len(same_signature) < 2:
                continue
            semantics = {
                str(item.get("dose_semantics", "not_applicable"))
                for item in same_signature
            }
            has_explicit_planned_label = any(
                item.get("dose_semantics") == "planned"
                and re.search(
                    r"(?:plan|planned|prescribed|target|计划|处方|目标)",
                    str(item.get("source_field", "")),
                    flags=re.IGNORECASE,
                )
                for item in same_signature
            )
            has_explicit_actual_label = any(
                item.get("dose_semantics") == "actual_administered"
                and re.search(
                    r"(?:actual|admin|given|received|实给|实际|给药)",
                    str(item.get("source_field", "")),
                    flags=re.IGNORECASE,
                )
                for item in same_signature
            )
            if (
                semantics == {"planned", "actual_administered"}
                and has_explicit_planned_label
                and has_explicit_actual_label
            ):
                continue
            ambiguous.update(id(item) for item in same_signature)
        for mapping in mappings:
            if not _mapping_is_dose_like(mapping):
                continue
            semantics = str(
                mapping.get("dose_semantics", "not_applicable")
            )
            if semantics in {"not_applicable", "unresolved"}:
                ambiguous.add(id(mapping))
            if id(mapping) not in ambiguous:
                continue
            mapping["dose_semantics"] = "unresolved"
            if str(mapping.get("recommended_role", "")).startswith("ip."):
                mapping["recommended_role"] = "ip.dose.unresolved"
            mapping["confidence"] = min(
                float(mapping.get("confidence", 0.0)),
                0.55,
            )
            _append_mapping_quality_note(
                mapping,
                action_code="dose_semantics_unresolved",
                uncertainty=(
                    "计划、处方、实际给药、重复或派生剂量语义未被来源"
                    "标签和代表值充分区分。"
                ),
                user_action=(
                    "请依据CRF字段标签、填表说明或同行关系确认剂量语义。"
                ),
            )

    @staticmethod
    def _validate_field_mapping_coverage(
        structured_payload: Dict[str, Any],
        input_payload: Dict[str, Any],
        candidate: _ProviderCandidate,
    ) -> None:
        field_profile = input_payload["field_profile"]
        expected_pairs = [
            (
                str(item["domain"]).strip(),
                str(item["field"]).strip(),
            )
            for item in field_profile["fields"]
        ]
        mapping_pairs = [
            (
                str(item["domain"]).strip(),
                str(item["source_field"]).strip(),
            )
            for item in structured_payload["field_mappings"]
        ]
        if len(mapping_pairs) != len(set(mapping_pairs)):
            raise MonitoringAiOutputValidationError(
                "field mappings must have unique (domain, source_field) pairs"
            )
        if set(mapping_pairs) != set(expected_pairs) or len(mapping_pairs) != len(
            expected_pairs
        ):
            missing_pairs = sorted(set(expected_pairs) - set(mapping_pairs))
            unexpected_pairs = sorted(set(mapping_pairs) - set(expected_pairs))
            raise MonitoringAiOutputValidationError(
                "field mappings must cover every input profile field exactly once; "
                f"missing={missing_pairs}; unexpected={unexpected_pairs}; "
                f"expected_count={len(expected_pairs)}; actual_count={len(mapping_pairs)}"
            )
        try:
            provenance = _ListingFieldMappingProvenance.model_validate(
                structured_payload.get("mapping_provenance")
            )
        except ValidationError as exc:
            raise MonitoringAiOutputValidationError(
                MonitoringAiService._controlled_validation_error_text(exc)
            ) from exc
        provenance_by_pair = {
            (item.domain.strip(), item.source_field.strip()): item
            for item in provenance.field_origins
        }
        if (
            set(provenance_by_pair) != set(expected_pairs)
            or len(provenance.field_origins) != len(expected_pairs)
        ):
            raise MonitoringAiOutputValidationError(
                "field mapping provenance must cover every profile field exactly once"
            )
        profile_by_pair = {
            (
                str(item["domain"]).strip(),
                str(item["field"]).strip(),
            ): item
            for item in field_profile["fields"]
        }
        evidence_by_id = {item.evidence_id: item for item in candidate.evidence}
        relationships = field_profile.get("relationships", [])
        fields_by_domain: Dict[str, set[str]] = {}
        for domain, field in expected_pairs:
            fields_by_domain.setdefault(domain, set()).add(field)
        chunk_domain = str(field_profile.get("domain", "")).strip()
        domain_field_names = field_profile.get("domain_field_names", [])
        if chunk_domain and isinstance(domain_field_names, list):
            fields_by_domain[chunk_domain] = {
                str(field).strip()
                for field in domain_field_names
                if str(field).strip()
            }
        for mapping in structured_payload["field_mappings"]:
            pair = (
                str(mapping["domain"]).strip(),
                str(mapping["source_field"]).strip(),
            )
            profile = profile_by_pair[pair]
            deterministic_decision = deterministic_metadata_decision(
                pair[0],
                pair[1],
            )
            origin = provenance_by_pair[pair]
            if deterministic_decision is not None and (
                mapping["field_kind"] != MonitoringFieldKind.SOURCE_METADATA.value
                or origin.origin != "deterministic_rule"
                or origin.rule_id != deterministic_decision.rule_id
                or origin.rule_version != DETERMINISTIC_METADATA_MAPPING_VERSION
            ):
                raise MonitoringAiOutputValidationError(
                    "deterministic EDC technical field "
                    f"{pair[0]}.{pair[1]} must retain its exact source_metadata "
                    "rule provenance"
                )
            if deterministic_decision is None and origin.origin != "independent_ai":
                raise MonitoringAiOutputValidationError(
                    "non-deterministic field mapping must retain independent-AI "
                    "provenance"
                )
            if (
                int(profile.get("non_empty_count", 0)) == 0
                and deterministic_decision is None
                and mapping["field_kind"] != MonitoringFieldKind.UNMAPPED.value
            ):
                raise MonitoringAiOutputValidationError(
                    f"all-empty profile field {pair[0]}.{pair[1]} must remain "
                    "unmapped without data-dictionary evidence"
                )
            linked_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in mapping["evidence_ids"]
                if evidence_id in evidence_by_id
            ]
            if not any(
                str(item.raw_fields.get("domain", "")).strip() == pair[0]
                and str(item.raw_fields.get("field", "")).strip() == pair[1]
                and item.raw_fields.get("inferred_type") == profile.get("inferred_type")
                for item in linked_evidence
            ):
                raise MonitoringAiOutputValidationError(
                    "field mapping evidence must match its exact profile field"
                )
            lineage = mapping.get("derivation_lineage") or {}
            lineage_sources = {
                str(value).strip() for value in lineage.get("source_fields", [])
            }
            if lineage_sources and not lineage_sources.issubset(
                fields_by_domain.get(pair[0], set())
            ):
                raise MonitoringAiOutputValidationError(
                    "mapping lineage source_fields must exist in the same "
                    "profile domain"
                )
            dictionary_version_field = str(
                lineage.get("dictionary_version_field", "")
            ).strip()
            if (
                dictionary_version_field
                and dictionary_version_field
                not in fields_by_domain.get(pair[0], set())
            ):
                raise MonitoringAiOutputValidationError(
                    "mapping dictionary_version_field must exist in the same "
                    "profile domain"
                )
            if mapping["field_kind"] == MonitoringFieldKind.STANDARDIZED_CODED.value:
                coding_system = str(lineage.get("coding_system", "")).strip()
                if _NON_SPECIFIC_CODING_SYSTEM_RE.search(coding_system):
                    raise MonitoringAiOutputValidationError(
                        "standardized coded mapping requires an explicit coding system"
                    )
                if pair[1] in lineage_sources:
                    raise MonitoringAiOutputValidationError(
                        "standardized coded mapping source_fields must not include "
                        "the target field itself"
                    )
                relevant_relationships = [
                    relationship
                    for relationship in relationships
                    if (
                        str(relationship.get("domain", "")).strip() == pair[0]
                        and pair[1]
                        in {
                            str(relationship.get("left_field", "")).strip(),
                            str(relationship.get("right_field", "")).strip(),
                        }
                        and relationship.get("relationship_type")
                        == "term_code_pair"
                    )
                ]
                if not relevant_relationships:
                    raise MonitoringAiOutputValidationError(
                        "standardized coded mapping requires same-row "
                        "term/code relationship evidence"
                    )
                counterpart_fields = {
                    (
                        str(relationship.get("right_field", "")).strip()
                        if str(relationship.get("left_field", "")).strip() == pair[1]
                        else str(relationship.get("left_field", "")).strip()
                    )
                    for relationship in relevant_relationships
                }
                if not counterpart_fields.intersection(lineage_sources):
                    raise MonitoringAiOutputValidationError(
                        "standardized coded mapping source_fields must include "
                        "the paired term/code counterpart"
                    )
                if not dictionary_version_field:
                    raise MonitoringAiOutputValidationError(
                        "standardized coded mapping requires an independent "
                        "dictionary_version_field"
                    )
                if (
                    dictionary_version_field == pair[1]
                    or dictionary_version_field in counterpart_fields
                    or not _DICTIONARY_VERSION_FIELD_RE.search(
                        dictionary_version_field
                    )
                ):
                    raise MonitoringAiOutputValidationError(
                        "dictionary_version_field must be an independent "
                        "version field, not the coded or term field"
                    )
                relationship_is_imperfect = any(
                    int(relationship.get(metric, 0)) > 0
                    for relationship in relevant_relationships
                    for metric in (
                        "left_only_count",
                        "right_only_count",
                        "left_values_with_multiple_right",
                        "right_values_with_multiple_left",
                    )
                )
                if relationship_is_imperfect and float(mapping["confidence"]) > 0.8:
                    raise MonitoringAiOutputValidationError(
                        "imperfect term/code pairing cannot exceed 0.8 confidence"
                    )
            elif (
                mapping["field_kind"]
                == MonitoringFieldKind.DETERMINISTIC_DERIVED.value
            ):
                formula = str(lineage.get("formula", "")).strip()
                if not formula or _UNCERTAIN_FORMULA_RE.search(formula):
                    raise MonitoringAiOutputValidationError(
                        "deterministic derived mapping requires an exact, "
                        "independently verified formula"
                    )
                raise MonitoringAiOutputValidationError(
                    "AI field profile contains no row-level derivation proof; "
                    "deterministic_derived requires explicit user confirmation "
                    "in the mapping draft"
                )

    @staticmethod
    def _structured_validation_diagnostics(
        exc: Exception,
    ) -> List[Dict[str, Any]]:
        if not isinstance(exc, MonitoringAiOutputValidationError):
            return []
        return [dict(item) for item in exc.diagnostics]

    @staticmethod
    def _controlled_validation_error_text(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            controlled = [
                {
                    "type": item.get("type", "validation_error"),
                    "path": ".".join(str(part) for part in item.get("loc", ())),
                    "message": item.get("msg", "invalid value"),
                }
                for item in exc.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            ]
            text = canonical_json(controlled)
        else:
            text = f"{type(exc).__name__}: {exc}"
        return text[:_CONTROLLED_VALIDATION_ERROR_LIMIT]

    def _fail_if_revision_changed(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        request_payload: Any,
        response_payload: Any,
        stage: str,
        response_model: str,
    ) -> Optional[MonitoringAiRunResult]:
        current_revision = self.current_revision_resolver(job).strip()
        if current_revision == job.input_revision_sha256:
            return None
        return self._stale_claimed_job(
            job,
            owner=owner,
            request_payload=request_payload,
            response_payload=response_payload,
            failure_message=(
                "monitoring AI input revision changed "
                f"{stage}; provider output was discarded"
            ),
            outcome="stale_input",
            response_model=response_model,
        )

    @staticmethod
    def _provider_response_model_without_assertion(provider: AiProvider) -> str:
        return str(
            getattr(provider, "response_model", "")
            or getattr(provider, "model_name", "")
        ).strip()

    @staticmethod
    def _monitoring_provider_env(runtime_env: Dict[str, str]) -> Dict[str, str]:
        env = dict(runtime_env)
        try:
            configured = float(
                env.get(
                    "MONITORING_AI_TIMEOUT_SECONDS",
                    env.get("WORKBENCH_AI_TIMEOUT_SECONDS", "300"),
                )
            )
        except ValueError:
            configured = DEFAULT_MONITORING_AI_TIMEOUT_SECONDS
        env["WORKBENCH_AI_TIMEOUT_SECONDS"] = str(
            max(DEFAULT_MONITORING_AI_TIMEOUT_SECONDS, configured)
        )
        return env

    def _parse_provider_output(
        self,
        job: MonitoringAiJob,
        output: Any,
        input_payload: Dict[str, Any],
    ) -> Tuple[MonitoringAiCandidate, ...]:
        try:
            parsed = _ProviderOutput.model_validate(output)
        except ValidationError as exc:
            raise MonitoringAiOutputValidationError(
                self._controlled_validation_error_text(exc)
            ) from exc
        if parsed.schema_version != MONITORING_AI_SCHEMA_VERSION:
            raise MonitoringAiOutputValidationError(
                "provider output schema version mismatch"
            )
        if (
            parsed.task_id != job.job_id
            or parsed.task_type != job.task_type
            or parsed.input_revision_sha256 != job.input_revision_sha256
        ):
            raise MonitoringAiOutputValidationError(
                "provider output does not match exact monitoring job input"
            )
        structured_payloads = self._validate_task_specific_output(
            job,
            parsed,
            input_payload,
        )
        created_at = self.repository.clock()
        candidates = tuple(
            self._candidate_from_provider(
                job,
                item,
                structured_payload,
                index,
                created_at,
            )
            for index, (item, structured_payload) in enumerate(
                zip(parsed.candidates, structured_payloads),
                start=1,
            )
        )
        try:
            validate_candidates_for_job(job, candidates)
        except ValueError as exc:
            raise MonitoringAiOutputValidationError(str(exc)) from exc
        return candidates

    @staticmethod
    def _candidate_from_provider(
        job: MonitoringAiJob,
        candidate: _ProviderCandidate,
        structured_payload: Dict[str, Any],
        index: int,
        created_at: datetime,
    ) -> MonitoringAiCandidate:
        evidence = tuple(
            MonitoringAiEvidence(
                evidence_id=item.evidence_id,
                source_entry_id=item.source_entry_id,
                source_content_sha256=item.source_content_sha256,
                locator=item.locator,
                quote=item.quote,
                raw_fields=item.raw_fields,
                input_revision_sha256=job.input_revision_sha256,
            )
            for item in candidate.evidence
        )
        claims = tuple(
            MonitoringAiClaim(
                claim_id=item.claim_id,
                kind=item.kind,
                text=item.text,
                confidence=item.confidence,
                uncertainty=item.uncertainty,
                user_action=item.user_action,
                evidence_ids=tuple(item.evidence_ids),
            )
            for item in candidate.claims
        )
        candidate_dump = candidate.model_dump(mode="json")
        if (
            job.task_type
            == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ):
            # Protocol candidate identity binds the server-normalized
            # structured payload (expanded evidence IDs plus typed repair
            # lineage/version), never the raw provider payload: identical
            # raw output under a different repair cannot silently retain
            # the same candidate identity.
            candidate_dump = {
                **candidate_dump,
                "structured_payload": structured_payload,
            }
        candidate_seed = {
            "job_id": job.job_id,
            "index": index,
            "candidate": candidate_dump,
        }
        candidate_id = "moncand_" + content_sha256(candidate_seed)[:28]
        return MonitoringAiCandidate(
            candidate_id=candidate_id,
            job_id=job.job_id,
            project_id=job.project_id,
            task_type=job.task_type,
            candidate_type=candidate.candidate_type,
            title=candidate.title,
            text=candidate.text,
            structured_payload=structured_payload,
            claims=claims,
            evidence=evidence,
            status=MonitoringAiCandidateStatus.PROPOSED,
            input_revision_sha256=job.input_revision_sha256,
            prompt_version=job.prompt_version,
            created_at=created_at,
        )

    def _run_with_heartbeat(
        self,
        job: MonitoringAiJob,
        owner: str,
        provider: AiProvider,
        envelope: AiPromptEnvelope,
    ) -> Dict[str, Any]:
        stop = threading.Event()
        heartbeat_error: List[Exception] = []
        interval = max(
            0.25,
            min(30.0, float(self.repository.lease_seconds) / 3.0),
        )

        def heartbeat_loop() -> None:
            while not stop.wait(interval):
                try:
                    self.repository.heartbeat(
                        job.project_id,
                        job.job_id,
                        owner,
                    )
                except Exception as exc:
                    heartbeat_error.append(exc)
                    return

        self.repository.heartbeat(job.project_id, job.job_id, owner)
        thread = threading.Thread(
            target=heartbeat_loop,
            name=f"monitoring-ai-heartbeat-{job.job_id[:12]}",
            daemon=True,
        )
        thread.start()
        try:
            output = provider.run(envelope)
        finally:
            stop.set()
            thread.join(timeout=max(1.0, interval + 0.5))
        if heartbeat_error:
            raise MonitoringAiStateConflictError(
                f"monitoring AI lease heartbeat failed: {heartbeat_error[0]}"
            )
        self.repository.heartbeat(job.project_id, job.job_id, owner)
        if not isinstance(output, dict):
            raise MonitoringAiOutputValidationError(
                "provider output must be a JSON object"
            )
        return output

    @staticmethod
    def _response_model(provider: AiProvider, job: MonitoringAiJob) -> str:
        expected = str(getattr(provider, "expected_response_model", "")).strip()
        actual = str(getattr(provider, "response_model", "")).strip()
        if not expected or expected != job.requested_model:
            raise MonitoringAiResponseIdentityError(
                "provider expected response model identity is missing or "
                "does not match the job"
            )
        if not actual or actual != expected:
            raise MonitoringAiResponseIdentityError(
                "provider response model identity is missing or mismatched"
            )
        return actual

    @staticmethod
    def _validate_runtime_transport(
        runtime: MonitoringAiRuntimeBinding,
    ) -> None:
        runtime_transport = runtime.transport.strip()
        env_transport = runtime.env.get(
            "WORKBENCH_AI_TRANSPORT",
            runtime_transport,
        ).strip()
        if (
            runtime_transport != MONITORING_PRODUCT_AI_TRANSPORT
            or env_transport != MONITORING_PRODUCT_AI_TRANSPORT
            or env_transport != runtime_transport
        ):
            raise MonitoringAiTransportRejectedError(
                "medical monitoring product AI only accepts "
                "openai_compatible transport"
            )
        if (
            runtime.env.get("WORKBENCH_AI_PROVIDER", "").strip()
            != runtime.provider
            or runtime.env.get("WORKBENCH_AI_MODEL", "").strip()
            != runtime.model
        ):
            raise MonitoringAiRuntimeUnavailableError(
                "independent AI runtime environment does not match the "
                "selected role/profile"
            )
        expected = runtime.env.get(
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL",
            "",
        ).strip()
        if expected != runtime.model:
            raise MonitoringAiResponseIdentityError(
                "independent AI expected response model identity is missing "
                "or mismatched"
            )
        status = ai_gateway_status_from_env(runtime.env)
        if (
            status.get("configured") is not True
            or status.get("semantic_ai_tasks_enabled") is not True
        ):
            raise MonitoringAiRuntimeUnavailableError(
                "independent AI role/profile is not currently runnable"
            )

    @staticmethod
    def _validate_runtime_matches_job(
        job: MonitoringAiJob,
        runtime: MonitoringAiRuntimeBinding,
    ) -> None:
        if (
            runtime.profile_id != job.profile_id
            or runtime.provider != job.provider
            or runtime.model != job.requested_model
        ):
            raise MonitoringAiRuntimeUnavailableError(
                "independent AI runtime binding changed after job submission; "
                "submit a new job against the current profile"
            )

    @staticmethod
    def _validate_provider_matches_job(
        job: MonitoringAiJob,
        provider: AiProvider,
    ) -> None:
        if (
            str(getattr(provider, "transport_name", "")).strip()
            != MONITORING_PRODUCT_AI_TRANSPORT
        ):
            raise MonitoringAiTransportRejectedError(
                "medical monitoring provider is not openai_compatible"
            )
        if (
            str(getattr(provider, "provider_name", "")).strip() != job.provider
            or str(getattr(provider, "model_name", "")).strip() != job.requested_model
        ):
            raise MonitoringAiRuntimeUnavailableError(
                "configured provider identity does not match the submitted job"
            )
        if (
            str(getattr(provider, "expected_response_model", "")).strip()
            != job.requested_model
        ):
            raise MonitoringAiResponseIdentityError(
                "configured provider expected response model does not match "
                "the submitted job"
            )

    def _fail_claimed_job(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        request_payload: Any,
        response_payload: Any,
        failure_code: str,
        failure_message: str,
        retryable: bool,
        outcome: str,
        response_model: str = "",
    ) -> MonitoringAiRunResult:
        try:
            self.repository.record_attempt(
                job,
                owner=owner,
                request_payload=request_payload,
                response_payload=response_payload,
                response_model=response_model,
                outcome=outcome,
                failure_code=failure_code,
                failure_message=failure_message,
            )
            failed = self.repository.fail(
                job,
                owner=owner,
                failure_code=failure_code,
                failure_message=failure_message,
                retryable=retryable,
            )
            return MonitoringAiRunResult(job=failed, processed=True)
        except MonitoringAiStateConflictError:
            return MonitoringAiRunResult(
                job=self._current_job_or_claim(job),
                processed=False,
                lease_lost=True,
            )

    def _stale_claimed_job(
        self,
        job: MonitoringAiJob,
        *,
        owner: str,
        request_payload: Any,
        response_payload: Any,
        failure_message: str,
        outcome: str,
        response_model: str = "",
    ) -> MonitoringAiRunResult:
        try:
            self.repository.record_attempt(
                job,
                owner=owner,
                request_payload=request_payload,
                response_payload=response_payload,
                response_model=response_model,
                outcome=outcome,
                failure_code="stale_input_revision",
                failure_message=failure_message,
            )
            stale = self.repository.stale_claimed(
                job,
                owner=owner,
                reason=failure_message,
            )
            return MonitoringAiRunResult(job=stale, processed=True)
        except MonitoringAiStateConflictError:
            return MonitoringAiRunResult(
                job=self._current_job_or_claim(job),
                processed=False,
                lease_lost=True,
            )

    def _current_job_or_claim(self, job: MonitoringAiJob) -> MonitoringAiJob:
        try:
            return self.repository.get(job.project_id, job.job_id)
        except Exception:
            return job

    @staticmethod
    def _validate_input_payload(
        task_type: MonitoringAiTaskType,
        project_id: str,
        input_revision: MonitoringAiInputRevision,
        input_payload: Dict[str, Any],
    ) -> None:
        if not isinstance(input_payload, dict) or not input_payload:
            raise ValueError("monitoring AI input payload must be a non-empty object")
        if not input_revision.sources:
            raise ValueError(
                "monitoring AI input revision requires at least one exact "
                "source binding"
            )
        if task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            evidence_packet = input_payload.get("evidence_packet")
            if not isinstance(evidence_packet, list) or not evidence_packet:
                raise ValueError(
                    "monitoring AI semantic task requires a non-empty "
                    "system evidence_packet"
                )
            if len(evidence_packet) > 200:
                raise ValueError(
                    "monitoring AI evidence_packet exceeds 200 items"
                )
            validated_evidence = [
                _ProviderEvidence.model_validate(item)
                for item in evidence_packet
            ]
            evidence_ids = [item.evidence_id for item in validated_evidence]
            if len(evidence_ids) != len(set(evidence_ids)):
                raise ValueError(
                    "monitoring AI evidence_packet IDs must be unique"
                )
            for evidence in validated_evidence:
                if (
                    evidence.source_entry_id,
                    evidence.source_content_sha256,
                ) not in input_revision.source_pairs:
                    raise ValueError(
                        "monitoring AI evidence_packet source/hash pair is "
                        "not in the exact input revision"
                    )
            if task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
                context = input_payload.get("rule_template_context")
                if not isinstance(context, dict):
                    raise ValueError(
                        "rule-template recommendation requires its frozen context"
                    )
                required_context = {
                    "contract_version",
                    "fact_snapshot",
                    "mapping_snapshot",
                    "allowed_fact_types",
                    "allowed_rule_families",
                    "available_closed_roles",
                    "fact_evidence_id",
                    "mapping_evidence_id",
                }
                missing_context = sorted(required_context.difference(context))
                if missing_context:
                    raise ValueError(
                        "rule-template context is incomplete: "
                        + ", ".join(missing_context)
                    )
                if (
                    context["contract_version"]
                    != "monitoring_rule_template_recommendation_v1"
                ):
                    raise ValueError(
                        "rule-template recommendation contract version mismatch"
                    )
                evidence_id_set = set(evidence_ids)
                if {
                    str(context["fact_evidence_id"]),
                    str(context["mapping_evidence_id"]),
                } - evidence_id_set:
                    raise ValueError(
                        "rule-template context evidence IDs are not authorized"
                    )
            return
        field_profile = input_payload.get("field_profile")
        if not isinstance(field_profile, dict):
            raise ValueError("listing field mapping requires field_profile object")
        required = {
            "schema_version",
            "batch_id",
            "project_id",
            "batch_revision",
            "row_count",
            "input_sha256",
            "fields",
            "profile_sha256",
            "source_bindings",
        }
        missing = sorted(required.difference(field_profile))
        if missing:
            raise ValueError(
                "listing field profile is incomplete: " + ", ".join(missing)
            )
        if field_profile["project_id"] != project_id:
            raise ValueError("listing field profile belongs to another project")
        source_bindings = field_profile["source_bindings"]
        if not isinstance(source_bindings, list) or not source_bindings:
            raise ValueError("listing field profile source_bindings must be non-empty")
        try:
            profile_source_pairs = {
                (
                    str(item["source_entry_id"]).strip(),
                    _require_service_sha256(
                        item["source_content_sha256"],
                        "listing field profile source_content_sha256",
                    ),
                )
                for item in source_bindings
            }
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "listing field profile source_bindings are malformed"
            ) from exc
        if len(profile_source_pairs) != len(source_bindings):
            raise ValueError("listing field profile source_bindings must be unique")
        _require_service_sha256(
            field_profile["input_sha256"],
            "listing field profile input_sha256",
        )
        _require_service_sha256(
            field_profile["profile_sha256"],
            "listing field profile profile_sha256",
        )
        revision_profile_sources = {
            pair
            for pair in input_revision.source_pairs
            if pair[0].startswith("field-profile:")
        }
        expected_profile_source = monitoring_field_profile_source_binding(
            field_profile["profile_sha256"]
        )
        if revision_profile_sources != {
            (
                expected_profile_source.source_entry_id,
                expected_profile_source.source_content_sha256,
            )
        }:
            raise ValueError(
                "listing field profile derived source does not match "
                "the exact input revision"
            )
        revision_raw_sources = input_revision.source_pairs.difference(
            revision_profile_sources
        )
        if profile_source_pairs != revision_raw_sources:
            raise ValueError(
                "listing field profile source_bindings do not match "
                "the exact input revision"
            )
        if not _is_non_bool_int(field_profile["row_count"]) or (
            field_profile["row_count"] <= 0
        ):
            raise ValueError("listing field profile row_count must be positive")
        fields = field_profile["fields"]
        if not isinstance(fields, list) or not fields:
            raise ValueError("listing field profile fields must be non-empty")
        field_pairs = []
        for field in fields:
            if (
                not isinstance(field, dict)
                or not str(field.get("domain", "")).strip()
                or not str(field.get("field", "")).strip()
            ):
                raise ValueError(
                    "every listing field profile requires domain and field"
                )
            field_pairs.append(
                (
                    str(field["domain"]).strip(),
                    str(field["field"]).strip(),
                )
            )
        if len(field_pairs) != len(set(field_pairs)):
            raise ValueError(
                "listing field profile (domain, field) pairs must be unique"
            )
        treatment_identity_bindings = field_profile.get(
            "treatment_identity_bindings",
            [],
        )
        if not isinstance(treatment_identity_bindings, list):
            raise ValueError(
                "listing treatment_identity_bindings must be a list"
            )
        binding_ids: list[str] = []
        all_profile_pairs = set(field_pairs)
        declared_binding_source_pairs = {
            (
                str(item.get("domain", "")).strip(),
                str(item.get("field", "")).strip(),
            )
            for item in field_profile.get(
                "treatment_identity_binding_source_pairs",
                [],
            )
            if isinstance(item, dict)
        }
        for binding in treatment_identity_bindings:
            try:
                validated_binding = _TreatmentIdentityBinding.model_validate(
                    binding
                )
            except ValidationError as exc:
                raise ValueError(
                    "listing treatment identity binding is malformed"
                ) from exc
            binding_ids.append(validated_binding.binding_id)
            source_pair = (
                validated_binding.source_domain,
                validated_binding.source_field,
            )
            if (
                source_pair not in all_profile_pairs
                and source_pair not in declared_binding_source_pairs
            ):
                raise ValueError(
                    "treatment identity binding references an unknown source field"
                )
            if not any(
                domain == validated_binding.target_domain
                for domain, _ in all_profile_pairs
            ):
                raise ValueError(
                    "treatment identity binding references an unknown target domain"
                )
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError(
                "listing treatment identity binding IDs must be unique"
            )
        relationships = field_profile.get("relationships", [])
        if not isinstance(relationships, list):
            raise ValueError("listing field profile relationships must be a list")
        relationship_keys = []
        current_field_pairs = set(field_pairs)
        for relationship in relationships:
            if not isinstance(relationship, dict):
                raise ValueError("listing field relationship must be an object")
            try:
                domain = str(relationship["domain"]).strip()
                left_field = str(relationship["left_field"]).strip()
                right_field = str(relationship["right_field"]).strip()
                relationship_type = str(
                    relationship["relationship_type"]
                ).strip()
            except KeyError as exc:
                raise ValueError(
                    "listing field relationship is incomplete"
                ) from exc
            if (
                not domain
                or not left_field
                or not right_field
                or left_field == right_field
                or relationship_type not in FIELD_RELATIONSHIP_TYPES
            ):
                raise ValueError("listing field relationship is malformed")
            relationship_keys.append(
                (domain, left_field, right_field, relationship_type)
            )
            numeric_keys = (
                "total_rows",
                "jointly_non_empty_count",
                "left_only_count",
                "right_only_count",
                "unique_pair_count",
                "left_values_with_multiple_right",
                "right_values_with_multiple_left",
            )
            if any(
                not _is_non_bool_int(relationship.get(key))
                or relationship[key] < 0
                for key in numeric_keys
            ):
                raise ValueError(
                    "listing field relationship counts must be "
                    "non-negative integers"
                )
            if (
                relationship["jointly_non_empty_count"]
                + relationship["left_only_count"]
                + relationship["right_only_count"]
                > relationship["total_rows"]
                or relationship["unique_pair_count"]
                > relationship["jointly_non_empty_count"]
            ):
                raise ValueError(
                    "listing field relationship counts are inconsistent"
                )
            relation_pairs = {
                (domain, left_field),
                (domain, right_field),
            }
            if field_profile.get("scope") == "complete_profile_chunk":
                if not relation_pairs.intersection(current_field_pairs):
                    raise ValueError(
                        "listing field relationship is unrelated to chunk"
                    )
            elif not relation_pairs.issubset(current_field_pairs):
                raise ValueError(
                    "listing field relationship references unknown field"
                )
        if len(relationship_keys) != len(set(relationship_keys)):
            raise ValueError("listing field relationships must be unique")
        if field_profile.get("scope") != "complete_profile_chunk":
            return

        chunk_required = {
            "full_profile_sha256",
            "full_input_sha256",
            "full_field_count",
            "domain",
            "domain_field_count",
            "domain_field_names",
            "chunk_index",
            "chunk_total",
            "chunk_size_limit",
        }
        chunk_missing = sorted(chunk_required.difference(field_profile))
        if chunk_missing:
            raise ValueError(
                "listing field profile chunk is incomplete: " + ", ".join(chunk_missing)
            )
        for full_key, original_key in (
            ("full_profile_sha256", "profile_sha256"),
            ("full_input_sha256", "input_sha256"),
        ):
            full_hash = _require_service_sha256(
                field_profile[full_key],
                f"listing field profile {full_key}",
            )
            original_hash = _require_service_sha256(
                field_profile[original_key],
                f"listing field profile {original_key}",
            )
            if full_hash != original_hash:
                raise ValueError(
                    f"listing field profile {full_key} must preserve {original_key}"
                )

        integer_fields = (
            "full_field_count",
            "domain_field_count",
            "chunk_index",
            "chunk_total",
            "chunk_size_limit",
        )
        if any(
            not _is_non_bool_int(field_profile[key])
            or field_profile[key] <= 0
            for key in integer_fields
        ):
            raise ValueError(
                "listing field profile chunk counts must be positive integers"
            )
        full_field_count = field_profile["full_field_count"]
        domain_field_count = field_profile["domain_field_count"]
        domain_field_names = field_profile["domain_field_names"]
        chunk_index = field_profile["chunk_index"]
        chunk_total = field_profile["chunk_total"]
        chunk_size_limit = field_profile["chunk_size_limit"]
        if not 1 <= chunk_index <= chunk_total:
            raise ValueError(
                "listing field profile chunk_index must be within chunk_total"
            )
        if not len(fields) <= domain_field_count <= full_field_count:
            raise ValueError(
                "listing field profile chunk field counts are inconsistent"
            )
        if (
            not isinstance(domain_field_names, list)
            or len(domain_field_names) != domain_field_count
            or any(not str(name).strip() for name in domain_field_names)
            or len({str(name).strip() for name in domain_field_names})
            != domain_field_count
        ):
            raise ValueError(
                "listing field profile domain_field_names must completely and "
                "uniquely describe the declared domain"
            )
        expected_chunk_total = (
            domain_field_count + chunk_size_limit - 1
        ) // chunk_size_limit
        if chunk_total != expected_chunk_total:
            raise ValueError(
                "listing field profile chunk_total does not match domain size"
            )
        expected_chunk_length = (
            chunk_size_limit
            if chunk_index < chunk_total
            else domain_field_count - chunk_size_limit * (chunk_total - 1)
        )
        if len(fields) != expected_chunk_length:
            raise ValueError(
                "listing field profile chunk does not contain its complete range"
            )
        chunk_domain = str(field_profile["domain"]).strip()
        if not chunk_domain:
            raise ValueError("listing field profile chunk domain is required")
        if any(pair[0] != chunk_domain for pair in field_pairs):
            raise ValueError(
                "listing field profile chunk may contain only its declared domain"
            )
        ordered_names = [pair[1] for pair in field_pairs]
        normalized_domain_names = [str(name).strip() for name in domain_field_names]
        if normalized_domain_names != sorted(
            normalized_domain_names,
            key=lambda value: (value.casefold(), value),
        ):
            raise ValueError(
                "listing field profile domain_field_names must be sorted by field"
            )
        if not set(ordered_names).issubset(set(normalized_domain_names)):
            raise ValueError(
                "listing field profile chunk fields must belong to "
                "domain_field_names"
            )
        domain_name_pairs = {
            (chunk_domain, field_name)
            for field_name in normalized_domain_names
        }
        for relationship in relationships:
            relation_pairs = {
                (
                    str(relationship["domain"]).strip(),
                    str(relationship["left_field"]).strip(),
                ),
                (
                    str(relationship["domain"]).strip(),
                    str(relationship["right_field"]).strip(),
                ),
            }
            if not relation_pairs.issubset(domain_name_pairs):
                raise ValueError(
                    "listing field relationship must stay within "
                    "domain_field_names"
                )
        if ordered_names != sorted(
            ordered_names,
            key=lambda value: (value.casefold(), value),
        ):
            raise ValueError(
                "listing field profile chunk fields must be sorted by field"
            )


def monitoring_ai_prompt_contract_digest() -> str:
    payload = {
        "deterministic_metadata_mapping_version": (
            DETERMINISTIC_METADATA_MAPPING_VERSION
        ),
        "role_catalog_version": ROLE_CATALOG_VERSION,
        "semantic_rule_catalog_version": RULE_CATALOG_VERSION,
        "versions": {
            task.value: version for task, version in PROMPT_VERSION_BY_TASK.items()
        },
        "task_contracts": {
            task.value: contract for task, contract in TASK_CONTRACTS.items()
        },
        "task_mapping": {
            task.value: mapped.value
            for task, mapped in AI_TASK_TYPE_BY_MONITORING_TASK.items()
        },
    }
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()
