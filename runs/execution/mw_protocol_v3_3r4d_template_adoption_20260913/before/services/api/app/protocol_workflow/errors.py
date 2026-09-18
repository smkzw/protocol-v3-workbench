"""Stable, user-explainable error contracts for the Protocol v3 workflow.

The registry is deliberately finite. Application services may raise a registered
error, but may not invent a free-text code at runtime. Public UI content and
audit detail use separate serializers so implementation traces never become
medical-writer-facing copy by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple, Union


ERROR_CODE_PATTERN = re.compile(
    r"^MW-PRO-(?P<gate>[A-Z][A-Z0-9]{0,7})-"
    r"(?P<object_type>[A-Z][A-Z0-9_]{0,31})-"
    r"(?P<cause>[A-Z][A-Z0-9_]{0,63})$"
)

GATE_PHASE: Mapping[str, int] = MappingProxyType(
    {
        "P0": 0,
        "P1": 1,
        "P2": 2,
        "P3": 3,
        "E0": 4,
        "E1": 4,
        "E2": 4,
        "E3": 4,
        "D1": 5,
        "W1": 6,
        "Q1": 7,
        "F1": 7,
        "R1": 8,
    }
)


class MalformedProtocolErrorCode(ValueError):
    """Raised when a code does not follow the canonical grammar."""


class UnknownProtocolErrorCode(LookupError):
    """Raised when a well-formed code is absent from the finite registry."""


class ProtocolErrorOwner(str, Enum):
    COORDINATOR_AGENT = "coordinator_agent"
    EVIDENCE_AGENT = "evidence_agent"
    DESIGN_AGENT = "design_agent"
    WRITING_AGENT = "writing_agent"
    QC_AGENT = "qc_agent"
    APPLICATION_SERVICE = "application_service"
    WORD_VALIDATION_SERVICE = "word_validation_service"


OWNER_PUBLIC_LABEL: Mapping[ProtocolErrorOwner, str] = MappingProxyType(
    {
        ProtocolErrorOwner.COORDINATOR_AGENT: "方案统筹",
        ProtocolErrorOwner.EVIDENCE_AGENT: "资料与证据整理",
        ProtocolErrorOwner.DESIGN_AGENT: "方案设计",
        ProtocolErrorOwner.WRITING_AGENT: "方案撰写",
        ProtocolErrorOwner.QC_AGENT: "方案审阅",
        ProtocolErrorOwner.APPLICATION_SERVICE: "工作台处理",
        ProtocolErrorOwner.WORD_VALIDATION_SERVICE: "Word 定稿核验",
    }
)


class RecoveryAction(str, Enum):
    REBUILD_SOURCE_BASELINE = "rebuild_source_baseline"
    COMPLETE_PROOF_OF_CONCEPT = "complete_proof_of_concept"
    RECONCILE_CANONICAL_STATE = "reconcile_canonical_state"
    REFRESH_STALE_REVISION = "refresh_stale_revision"
    RECOVER_PROVIDER_RESULT = "recover_provider_result"
    REBUILD_FROM_DOMAIN_EVENTS = "rebuild_from_domain_events"
    COMPLETE_TEMPLATE_MAPPING = "complete_template_mapping"
    COMPLETE_SERVICE_CONFIGURATION = "complete_service_configuration"
    COMPLETE_AI_CONFIGURATION = "complete_ai_configuration"
    REVISE_SEARCH_SCOPE = "revise_search_scope"
    COMPLETE_SOURCE_PROCESSING = "complete_source_processing"
    UPDATE_GUIDANCE_EVIDENCE = "update_guidance_evidence"
    COMPLETE_MEDICAL_ADMISSION = "complete_medical_admission"
    RESOLVE_DESIGN_DECISION = "resolve_design_decision"
    REPAIR_CHAPTER_CONTENT = "repair_chapter_content"
    REPAIR_QC_FINDINGS = "repair_qc_findings"
    REFRESH_WORD_RECEIPT = "refresh_word_receipt"
    REBUILD_SUBMISSION_PACKAGE = "rebuild_submission_package"
    RECONCILE_SHADOW_RESULT = "reconcile_shadow_result"
    COMPLETE_E2E_ARTIFACTS = "complete_e2e_artifacts"
    HOLD_RELEASE = "hold_release"


class ProtocolErrorCode(str, Enum):
    P0_SOURCE_BASELINE_MISMATCH = "MW-PRO-P0-SOURCE-BASELINE_MISMATCH"
    P0_EDITOR_POC_NOT_ACCEPTED = "MW-PRO-P0-EDITOR-POC_NOT_ACCEPTED"
    P0_WORD_PRODUCER_UNAVAILABLE = "MW-PRO-P0-WORD-PRODUCER_UNAVAILABLE"

    P1_OBJECT_NOT_FOUND = "MW-PRO-P1-OBJECT-NOT_FOUND"
    P1_SERVICE_CONFIGURATION_INCOMPLETE = "MW-PRO-P1-SERVICE-CONFIGURATION_INCOMPLETE"
    P1_DECISION_CAS = "MW-PRO-P1-DECISION-CAS"
    P1_REVISION_STALE = "MW-PRO-P1-REVISION-STALE"
    P1_EXECUTION_UNKNOWN_OUTCOME = "MW-PRO-P1-EXECUTION-UNKNOWN_OUTCOME"
    P1_CHECKPOINT_EVENT_MISMATCH = (
        "MW-PRO-P1-CHECKPOINT-CHECKPOINT_EVENT_MISMATCH"
    )

    P2_TEMPLATE_MAPPING_INCOMPLETE = "MW-PRO-P2-TEMPLATE-MAPPING_INCOMPLETE"
    P2_CHAPTER_CONTRACT_INCOMPLETE = "MW-PRO-P2-CHAPTER-CONTRACT_INCOMPLETE"

    P3_AI_CONFIGURATION_INCOMPLETE = "MW-PRO-P3-AI-CONFIGURATION_INCOMPLETE"
    P3_SKILL_PIN_MISMATCH = "MW-PRO-P3-SKILL-PIN_MISMATCH"

    E0_SEARCH_SCOPE_INCOMPLETE = "MW-PRO-E0-SEARCH-SCOPE_INCOMPLETE"
    E0_ZERO_RESULT_UNEXPLAINED = "MW-PRO-E0-SEARCH-ZERO_RESULT_UNEXPLAINED"
    E1_PROTOCOL_DOWNLOAD_INCOMPLETE = "MW-PRO-E1-PROTOCOL-DOWNLOAD_INCOMPLETE"
    E1_SOURCE_UNREADABLE = "MW-PRO-E1-SOURCE-OCR_UNREADABLE"
    E1_TRANSLATION_FIDELITY_BLOCKED = (
        "MW-PRO-E1-TRANSLATION-FIDELITY_BLOCKED"
    )
    E2_GUIDANCE_VERSION_UNRESOLVED = (
        "MW-PRO-E2-GUIDANCE-CURRENT_VERSION_UNRESOLVED"
    )
    E3_MEDICAL_ADMISSION_INCOMPLETE = (
        "MW-PRO-E3-EVIDENCE-MEDICAL_ADMISSION_INCOMPLETE"
    )
    E3_CHAPTER_COVERAGE_INCOMPLETE = (
        "MW-PRO-E3-CHAPTER-EVIDENCE_COVERAGE_INCOMPLETE"
    )

    D1_STUDY_DEFINITION_INCOMPLETE = (
        "MW-PRO-D1-STUDY-DEFINITION_INCOMPLETE"
    )
    D1_RECOMMENDATION_EVIDENCE_UNRESOLVED = (
        "MW-PRO-D1-RECOMMENDATION-EVIDENCE_UNRESOLVED"
    )

    W1_CHAPTER_CONTENT_MISSING = (
        "MW-PRO-W1-CHAPTER-SUBSTANTIVE_CONTENT_MISSING"
    )
    W1_DOCUMENT_INTERNAL_TRACE_PRESENT = (
        "MW-PRO-W1-DOCUMENT-INTERNAL_TRACE_PRESENT"
    )
    W1_CHAPTER_DEPENDENCY_CHANGED = (
        "MW-PRO-W1-CHAPTER-DEPENDENCY_CHANGED"
    )

    Q1_FINDINGS_OPEN = "MW-PRO-Q1-DOCUMENT-QC_FINDINGS_OPEN"
    Q1_CROSS_CHAPTER_INCONSISTENT = (
        "MW-PRO-Q1-DOCUMENT-CROSS_CHAPTER_INCONSISTENT"
    )
    F1_WORD_RECEIPT_STALE = "MW-PRO-F1-WORD-WORD_RECEIPT_STALE"
    F1_WORD_NATIVE_VALIDATION_FAILED = (
        "MW-PRO-F1-WORD-NATIVE_VALIDATION_FAILED"
    )
    F1_SUBMISSION_PACKAGE_INCOMPLETE = (
        "MW-PRO-F1-PACKAGE-SUBMISSION_EVIDENCE_INCOMPLETE"
    )

    R1_SHADOW_RESULT_DIVERGED = "MW-PRO-R1-SHADOW-RESULT_DIVERGED"
    R1_E2E_ARTIFACT_INCOMPLETE = "MW-PRO-R1-E2E-ARTIFACT_INCOMPLETE"
    R1_RELEASE_ACCEPTANCE_INCOMPLETE = (
        "MW-PRO-R1-RELEASE-ACCEPTANCE_INCOMPLETE"
    )


@dataclass(frozen=True)
class ErrorCodeParts:
    gate: str
    object_type: str
    cause: str

    @property
    def code(self) -> str:
        return f"MW-PRO-{self.gate}-{self.object_type}-{self.cause}"


def parse_error_code(value: str) -> ErrorCodeParts:
    """Parse the canonical code grammar without consulting the registry."""

    if not isinstance(value, str):
        raise MalformedProtocolErrorCode("error code must be a string")
    match = ERROR_CODE_PATTERN.fullmatch(value)
    if match is None:
        raise MalformedProtocolErrorCode(
            "error code must follow MW-PRO-<GATE>-<OBJECT>-<CAUSE>"
        )
    gate = match.group("gate")
    if gate not in GATE_PHASE:
        raise MalformedProtocolErrorCode(f"unsupported Protocol gate: {gate}")
    return ErrorCodeParts(
        gate=gate,
        object_type=match.group("object_type"),
        cause=match.group("cause"),
    )


@dataclass(frozen=True)
class ProtocolErrorDefinition:
    code: ProtocolErrorCode
    phase: int
    owner: ProtocolErrorOwner
    retryable: bool
    recovery_action: RecoveryAction
    public_message: str
    public_next_step: str

    def __post_init__(self) -> None:
        parts = parse_error_code(self.code.value)
        expected_phase = GATE_PHASE[parts.gate]
        if self.phase != expected_phase:
            raise ValueError(
                f"phase {self.phase} does not match {parts.gate} ({expected_phase})"
            )
        if not isinstance(self.owner, ProtocolErrorOwner):
            raise ValueError("owner is required and must be a ProtocolErrorOwner")
        if type(self.retryable) is not bool:
            raise ValueError("retryable is required and must be a boolean")
        if not isinstance(self.recovery_action, RecoveryAction):
            raise ValueError("recovery_action is required")
        _validate_public_copy(self.public_message, field_name="public_message")
        _validate_public_copy(self.public_next_step, field_name="public_next_step")


_PUBLIC_COPY_FORBIDDEN = (
    "mw-pro-",
    "prompt",
    "api_key",
    "password",
    "token",
    "credential",
    "secret",
    "authorization",
    "bearer ",
    "checkpoint",
    "backend",
    "traceback",
    "错误码",
    "日志",
    "凭证",
    "产物",
    "基线",
    "构建",
    "log",
    "gate",
    "\\",
    "/",
)


def _validate_public_copy(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    if value != value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{field_name} must be a single trimmed line")
    if re.search(r"[\u3400-\u9fff]", value) is None:
        raise ValueError(f"{field_name} must contain native Chinese copy")
    lowered = value.casefold()
    for token in _PUBLIC_COPY_FORBIDDEN:
        if token.casefold() in lowered:
            raise ValueError(f"{field_name} contains internal implementation wording")


def _definition(
    code: ProtocolErrorCode,
    *,
    owner: ProtocolErrorOwner,
    retryable: bool,
    recovery_action: RecoveryAction,
    public_message: str,
    public_next_step: str,
) -> ProtocolErrorDefinition:
    parts = parse_error_code(code.value)
    return ProtocolErrorDefinition(
        code=code,
        phase=GATE_PHASE[parts.gate],
        owner=owner,
        retryable=retryable,
        recovery_action=recovery_action,
        public_message=public_message,
        public_next_step=public_next_step,
    )


_DEFINITIONS: Tuple[ProtocolErrorDefinition, ...] = (
    _definition(ProtocolErrorCode.P0_SOURCE_BASELINE_MISMATCH, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.REBUILD_SOURCE_BASELINE, public_message="当前写作依据与已确认的资料版本不一致，暂不能继续生成方案。", public_next_step="请先恢复已确认的资料版本，并重新核对写作依据。"),
    _definition(ProtocolErrorCode.P0_EDITOR_POC_NOT_ACCEPTED, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.COMPLETE_PROOF_OF_CONCEPT, public_message="正文编辑能力尚未完成真实文档验证，暂不能进入正式写作。", public_next_step="请先完成编辑器与样例文档的完整验证。"),
    _definition(ProtocolErrorCode.P0_WORD_PRODUCER_UNAVAILABLE, owner=ProtocolErrorOwner.WORD_VALIDATION_SERVICE, retryable=True, recovery_action=RecoveryAction.COMPLETE_PROOF_OF_CONCEPT, public_message="Word 定稿核验暂不可用，当前内容不会被标记为可提交版本。", public_next_step="请稍后重新进行 Word 定稿核验。"),
    _definition(ProtocolErrorCode.P1_OBJECT_NOT_FOUND, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.RECONCILE_CANONICAL_STATE, public_message="未找到所请求的方案工作流对象。", public_next_step="请核对项目与对象标识后重新请求。"),
    _definition(ProtocolErrorCode.P1_SERVICE_CONFIGURATION_INCOMPLETE, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.COMPLETE_SERVICE_CONFIGURATION, public_message="工作台配置尚未就绪，本次操作未执行。", public_next_step="请修复工作台配置后继续。"),
    _definition(ProtocolErrorCode.P1_DECISION_CAS, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=True, recovery_action=RecoveryAction.RECONCILE_CANONICAL_STATE, public_message="您查看的推荐已被更新，本次选择尚未应用。", public_next_step="请查看最新推荐后重新确认。"),
    _definition(ProtocolErrorCode.P1_REVISION_STALE, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=True, recovery_action=RecoveryAction.REFRESH_STALE_REVISION, public_message="当前页面不是方案的最新版本，本次修改尚未应用。", public_next_step="请刷新至最新版本后继续。"),
    _definition(ProtocolErrorCode.P1_EXECUTION_UNKNOWN_OUTCOME, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.RECOVER_PROVIDER_RESULT, public_message="本次智能处理结果尚未确认，系统不会重复生成或覆盖已有内容。", public_next_step="请先恢复本次处理结果，再决定是否重新执行。"),
    _definition(ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.REBUILD_FROM_DOMAIN_EVENTS, public_message="工作进度与已完成内容不一致，系统已停止后续处理。", public_next_step="请以已确认的研究事实和方案内容为准，重新恢复工作进度。"),
    _definition(ProtocolErrorCode.P2_TEMPLATE_MAPPING_INCOMPLETE, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.COMPLETE_TEMPLATE_MAPPING, public_message="方案模板的部分章节尚未明确对应的写作要求，暂不能开始正式写作。", public_next_step="请先补全相关章节的写作与核查要求。"),
    _definition(ProtocolErrorCode.P2_CHAPTER_CONTRACT_INCOMPLETE, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.COMPLETE_TEMPLATE_MAPPING, public_message="部分适用章节缺少明确的写作与核查要求。", public_next_step="请先补全相关章节要求。"),
    _definition(ProtocolErrorCode.P3_AI_CONFIGURATION_INCOMPLETE, owner=ProtocolErrorOwner.APPLICATION_SERVICE, retryable=False, recovery_action=RecoveryAction.COMPLETE_AI_CONFIGURATION, public_message="本次工作所需的智能能力尚未配置完整。", public_next_step="请先完成缺失能力的配置并核对可用状态。"),
    _definition(ProtocolErrorCode.P3_SKILL_PIN_MISMATCH, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.COMPLETE_AI_CONFIGURATION, public_message="本次任务使用的写作能力版本与启动时不一致。", public_next_step="请保留已完成内容，并使用一致版本重新开始任务。"),
    _definition(ProtocolErrorCode.E0_SEARCH_SCOPE_INCOMPLETE, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.REVISE_SEARCH_SCOPE, public_message="竞品与证据检索范围尚不完整，当前资料不足以支持方案设计。", public_next_step="请完善适应症、人群、机制和研究阶段后重新检索。"),
    _definition(ProtocolErrorCode.E0_ZERO_RESULT_UNEXPLAINED, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.REVISE_SEARCH_SCOPE, public_message="当前未获得可用的竞品方案，原因尚未核实。", public_next_step="请先核查检索词、疾病亚组和资料来源，再决定下一步。"),
    _definition(ProtocolErrorCode.E1_PROTOCOL_DOWNLOAD_INCOMPLETE, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_SOURCE_PROCESSING, public_message="已发现的竞品方案仍有文件未完整获取。", public_next_step="请完成全部可获取方案的下载与完整性核对。"),
    _definition(ProtocolErrorCode.E1_SOURCE_UNREADABLE, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_SOURCE_PROCESSING, public_message="部分资料内容尚不能准确识别，暂不用于方案设计。", public_next_step="请重新识别并核对原文完整性。"),
    _definition(ProtocolErrorCode.E1_TRANSLATION_FIDELITY_BLOCKED, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_SOURCE_PROCESSING, public_message="部分外文资料的中文内容尚未通过准确性核对。", public_next_step="请完成翻译复核后再纳入方案依据。"),
    _definition(ProtocolErrorCode.E2_GUIDANCE_VERSION_UNRESOLVED, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.UPDATE_GUIDANCE_EVIDENCE, public_message="现行法规、指导原则或共识的适用版本尚未确认。", public_next_step="请核对最新版本、适用范围及替代关系。"),
    _definition(ProtocolErrorCode.E3_MEDICAL_ADMISSION_INCOMPLETE, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_MEDICAL_ADMISSION, public_message="部分资料尚未完成医学适用性核查。", public_next_step="请完成来源、适用人群和可复用范围的核对。"),
    _definition(ProtocolErrorCode.E3_CHAPTER_COVERAGE_INCOMPLETE, owner=ProtocolErrorOwner.EVIDENCE_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_MEDICAL_ADMISSION, public_message="部分适用章节仍缺少可追溯的写作依据。", public_next_step="请补充并核对缺失章节的证据。"),
    _definition(ProtocolErrorCode.D1_STUDY_DEFINITION_INCOMPLETE, owner=ProtocolErrorOwner.DESIGN_AGENT, retryable=True, recovery_action=RecoveryAction.RESOLVE_DESIGN_DECISION, public_message="关键研究设计尚未形成完整且一致的结论。", public_next_step="请查看待处理的设计问题和推荐选项。"),
    _definition(ProtocolErrorCode.D1_RECOMMENDATION_EVIDENCE_UNRESOLVED, owner=ProtocolErrorOwner.DESIGN_AGENT, retryable=True, recovery_action=RecoveryAction.RESOLVE_DESIGN_DECISION, public_message="部分设计推荐缺少足够依据或存在未解释分歧。", public_next_step="请比较推荐理由和备选方案后确认。"),
    _definition(ProtocolErrorCode.W1_CHAPTER_CONTENT_MISSING, owner=ProtocolErrorOwner.WRITING_AGENT, retryable=True, recovery_action=RecoveryAction.REPAIR_CHAPTER_CONTENT, public_message="部分适用章节尚未形成可直接审阅的实质内容。", public_next_step="请补全相关章节并重新进行全文核对。"),
    _definition(ProtocolErrorCode.W1_DOCUMENT_INTERNAL_TRACE_PRESENT, owner=ProtocolErrorOwner.WRITING_AGENT, retryable=True, recovery_action=RecoveryAction.REPAIR_CHAPTER_CONTENT, public_message="方案正文仍含不应出现在定稿中的内部说明。", public_next_step="请清理相关内容并重新核对全文。"),
    _definition(ProtocolErrorCode.W1_CHAPTER_DEPENDENCY_CHANGED, owner=ProtocolErrorOwner.WRITING_AGENT, retryable=True, recovery_action=RecoveryAction.REPAIR_CHAPTER_CONTENT, public_message="上游设计变化影响了已完成章节，相关章节已重新开放。", public_next_step="请查看受影响内容并接受或调整新的推荐。"),
    _definition(ProtocolErrorCode.Q1_FINDINGS_OPEN, owner=ProtocolErrorOwner.QC_AGENT, retryable=True, recovery_action=RecoveryAction.REPAIR_QC_FINDINGS, public_message="方案仍有需要实质修订的问题，暂不能标记为可提交定稿。", public_next_step="请完成已定位问题的修订并重新审阅。"),
    _definition(ProtocolErrorCode.Q1_CROSS_CHAPTER_INCONSISTENT, owner=ProtocolErrorOwner.QC_AGENT, retryable=True, recovery_action=RecoveryAction.REPAIR_QC_FINDINGS, public_message="方案不同章节之间仍有设计或表述不一致。", public_next_step="请按已定位的关联章节完成一致性修订。"),
    _definition(ProtocolErrorCode.F1_WORD_RECEIPT_STALE, owner=ProtocolErrorOwner.WORD_VALIDATION_SERVICE, retryable=True, recovery_action=RecoveryAction.REFRESH_WORD_RECEIPT, public_message="Word 核验结果对应的不是当前方案版本。", public_next_step="请对当前版本重新完成 Word 核验。"),
    _definition(ProtocolErrorCode.F1_WORD_NATIVE_VALIDATION_FAILED, owner=ProtocolErrorOwner.WORD_VALIDATION_SERVICE, retryable=True, recovery_action=RecoveryAction.REFRESH_WORD_RECEIPT, public_message="当前 Word 文件尚未通过目录、交叉引用或版式核验。", public_next_step="请修订已定位的问题后重新核验。"),
    _definition(ProtocolErrorCode.F1_SUBMISSION_PACKAGE_INCOMPLETE, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=True, recovery_action=RecoveryAction.REBUILD_SUBMISSION_PACKAGE, public_message="可提交定稿所需的依据和核验记录尚未汇总完整。", public_next_step="请补齐缺失的依据和核验记录后重新生成定稿文件。"),
    _definition(ProtocolErrorCode.R1_SHADOW_RESULT_DIVERGED, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.RECONCILE_SHADOW_RESULT, public_message="新旧流程对同一项目产生了需要进一步核对的差异。", public_next_step="请先完成差异归因，再决定是否切换新流程。"),
    _definition(ProtocolErrorCode.R1_E2E_ARTIFACT_INCOMPLETE, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=True, recovery_action=RecoveryAction.COMPLETE_E2E_ARTIFACTS, public_message="本轮真实使用验证未形成完整方案和定稿证据。", public_next_step="请从中断位置继续完成真实使用验证，并核对完整方案和定稿结果。"),
    _definition(ProtocolErrorCode.R1_RELEASE_ACCEPTANCE_INCOMPLETE, owner=ProtocolErrorOwner.COORDINATOR_AGENT, retryable=False, recovery_action=RecoveryAction.HOLD_RELEASE, public_message="面向正式使用的验收条件尚未全部满足。", public_next_step="请保持当前版本不发布，并继续完成未通过项目。"),
)


def _build_catalog() -> Mapping[ProtocolErrorCode, ProtocolErrorDefinition]:
    catalog: Dict[ProtocolErrorCode, ProtocolErrorDefinition] = {}
    for definition in _DEFINITIONS:
        if definition.code in catalog:
            raise ValueError(f"duplicate Protocol error code: {definition.code.value}")
        catalog[definition.code] = definition
    missing = set(ProtocolErrorCode) - set(catalog)
    if missing:
        raise ValueError(f"Protocol error definitions missing: {sorted(m.value for m in missing)}")
    phases = {definition.phase for definition in catalog.values()}
    if phases != set(range(9)):
        raise ValueError(f"Protocol error catalog must cover phases 0-8, got {phases}")
    return MappingProxyType(catalog)


ERROR_CATALOG = _build_catalog()


def get_error_definition(
    code: Union[str, ProtocolErrorCode],
) -> ProtocolErrorDefinition:
    if isinstance(code, ProtocolErrorCode):
        canonical = code
    else:
        parse_error_code(code)
        try:
            canonical = ProtocolErrorCode(code)
        except ValueError as exc:
            raise UnknownProtocolErrorCode(code) from exc
    return ERROR_CATALOG[canonical]


class ProtocolWorkflowError(RuntimeError):
    """Typed workflow failure with deliberately separated UI/audit views."""

    __slots__ = (
        "_definition",
        "_object_id",
        "_owner",
        "_retryable",
        "_attempt",
        "_audit_detail",
        "_audit_context",
        "_sealed",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        # Python context managers must restore exception bookkeeping on re-raise.
        # Keep the workflow payload fixed without breaking exception propagation.
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        if getattr(self, "_sealed", False):
            raise AttributeError("ProtocolWorkflowError is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        code: Union[str, ProtocolErrorCode],
        object_id: str,
        owner: ProtocolErrorOwner,
        retryable: bool,
        attempt: int,
        audit_detail: str,
        audit_context: Optional[Mapping[str, Any]] = None,
    ) -> None:
        definition = get_error_definition(code)
        if not isinstance(object_id, str) or not object_id.strip():
            raise ValueError("object_id is required")
        if object_id != object_id.strip():
            raise ValueError("object_id must be trimmed")
        if not isinstance(owner, ProtocolErrorOwner):
            raise ValueError("owner is required and must be a ProtocolErrorOwner")
        if owner is not definition.owner:
            raise ValueError("owner must match the registered error definition")
        if type(retryable) is not bool:
            raise ValueError("retryable is required and must be a boolean")
        if retryable is not definition.retryable:
            raise ValueError("retryable must match the registered error definition")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(audit_detail, str) or not audit_detail.strip():
            raise ValueError("audit_detail is required")
        if audit_context is not None and not isinstance(audit_context, Mapping):
            raise ValueError("audit_context must be a mapping")

        self._definition = definition
        self._object_id = object_id
        self._owner = owner
        self._retryable = retryable
        self._attempt = attempt
        self._audit_detail = audit_detail.strip()
        self._audit_context = MappingProxyType(dict(audit_context or {}))
        super().__init__(definition.public_message)
        self._sealed = True

    @property
    def definition(self) -> ProtocolErrorDefinition:
        return self._definition

    @property
    def object_id(self) -> str:
        return self._object_id

    @property
    def owner(self) -> ProtocolErrorOwner:
        return self._owner

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def audit_detail(self) -> str:
        return self._audit_detail

    @property
    def audit_context(self) -> Mapping[str, Any]:
        return self._audit_context

    @property
    def code(self) -> ProtocolErrorCode:
        return self.definition.code

    def to_public_payload(self) -> Dict[str, Any]:
        """Return only content intended for the medical-writer interface."""

        return {
            "message": self.definition.public_message,
            "responsible_area": OWNER_PUBLIC_LABEL[self.owner],
            "can_retry": self.retryable,
            "next_step": self.definition.public_next_step,
        }

    def to_audit_payload(self) -> Dict[str, Any]:
        """Return the complete machine/audit record for controlled persistence."""

        return {
            "error_code": self.code.value,
            "phase": self.definition.phase,
            "object_id": self.object_id,
            "owner": self.owner.value,
            "retryable": self.retryable,
            "recovery_action": self.definition.recovery_action.value,
            "attempt": self.attempt,
            "audit_detail": self.audit_detail,
            "audit_context": dict(self.audit_context),
        }


__all__ = [
    "ERROR_CATALOG",
    "ERROR_CODE_PATTERN",
    "ErrorCodeParts",
    "MalformedProtocolErrorCode",
    "OWNER_PUBLIC_LABEL",
    "ProtocolErrorCode",
    "ProtocolErrorDefinition",
    "ProtocolErrorOwner",
    "ProtocolWorkflowError",
    "RecoveryAction",
    "UnknownProtocolErrorCode",
    "get_error_definition",
    "parse_error_code",
]
