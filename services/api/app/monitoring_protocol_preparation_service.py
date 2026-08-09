from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiEvidence,
    MonitoringAiJob,
    MonitoringAiJobStatus,
    MonitoringAiTaskType,
    candidate_confidence_summary,
    content_sha256,
)
from .monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiRepositoryError,
    MonitoringAiStateConflictError,
)
from .monitoring_ai_service import (
    PROMPT_VERSION_BY_TASK,
    MonitoringAiService,
)
from .monitoring_ai_source_packet import (
    MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS,
    PROTOCOL_EVIDENCE_PACKET_VERSION,
)
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
    MonitoringProtocolStateConflictError,
    ProtocolVersionConflictError,
)
from .monitoring_protocol_preparation_contract import (
    PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    PROTOCOL_PREPARATION_CONTRACT_VERSION,
)
from .monitoring_protocol_rules import (
    MonitoringProtocolRuleError,
    ProtocolFact,
    ProtocolSourceVersion,
)
from .monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)

_ESTIMAND_MARKERS = re.compile(
    r"(?:估计目标|estimand|主要疗效终点.{0,20}目标人群|目标人群.{0,20}主要疗效终点)",
    re.IGNORECASE,
)
_ELIGIBILITY_MARKERS = re.compile(
    r"(?:入选标准|纳入标准|排除标准|筛选期|筛选访视|随机前|给药前.{0,8}资格)",
    re.IGNORECASE,
)
_MODALITY_PATTERNS = (
    ("required", re.compile(r"(?:必须|应当|需|须|应该)")),
    (
        "optional",
        re.compile(
            r"(?:可以|可考虑|可予|可暂停|允许|"
            r"可(?=(?:停用|停药|停止给药|终止给药|重新给药|恢复给药|"
            r"重新开始|重启|剂量调整|调整剂量|减量|增加剂量)))"
        ),
    ),
    ("prohibited", re.compile(r"(?:不得|禁止|严禁)")),
)
_ACTION_PATTERNS = (
    (
        "permanent_stop",
        re.compile(r"(?:永久停药|永久停用|永久停止给药)"),
    ),
    (
        "temporary_stop",
        re.compile(r"(?:暂停给药|暂停用药|暂时停用|中断给药)"),
    ),
    (
        "stop",
        re.compile(r"(?:停用|停药|停止给药|终止给药)"),
    ),
    (
        "restart",
        re.compile(r"(?:重新给药|恢复给药|重新开始|重启)"),
    ),
    (
        "dose_adjustment",
        re.compile(r"(?:剂量调整|调整剂量|减量|增加剂量)"),
    ),
)
_IP_OBJECT_RE = re.compile(r"(?:研究药物|试验药物|研究治疗|试验用药)")
_CM_OBJECT_RE = re.compile(r"(?:合并用药|伴随用药|非试验用药|合并治疗)")


def _strict_evidence_bool(
    value: Any,
    field: str,
    *,
    default: bool,
) -> bool:
    """Accept an actual Boolean and reject truthy strings/numbers."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise MonitoringProtocolPreparationError(
        "monitoring_protocol_evidence_context_invalid",
        f"方案证据上下文 {field} 必须为布尔值。",
    )


PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS = frozenset(
    {
        "monitoring-protocol-clause-structuring-v3",
        "monitoring-protocol-clause-structuring-v4",
        "monitoring-protocol-clause-structuring-v5",
        "monitoring-protocol-clause-structuring-v6",
        "monitoring-protocol-clause-structuring-v7",
        "monitoring-protocol-clause-structuring-v8",
    }
)
# Startup retirement-audit set, deliberately distinct from the status
# compatibility set: completed and failed jobs of these prompt versions keep
# their status, failure evidence, timestamps, attempts and candidates during
# a prompt-version cutover while receiving the immutable contract-retirement
# marker. v9, v10 and v11 are included here for terminal audit preservation but
# are deliberately absent from PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS, so
# v9/v10/v11 history is never status-compatible, retryable or reusable under
# the current contract.
PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS = frozenset(
    {
        "monitoring-protocol-clause-structuring-v3",
        "monitoring-protocol-clause-structuring-v4",
        "monitoring-protocol-clause-structuring-v5",
        "monitoring-protocol-clause-structuring-v6",
        "monitoring-protocol-clause-structuring-v7",
        "monitoring-protocol-clause-structuring-v8",
        "monitoring-protocol-clause-structuring-v9",
        "monitoring-protocol-clause-structuring-v10",
        "monitoring-protocol-clause-structuring-v11",
    }
)


class MonitoringProtocolPreparationError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class MonitoringProtocolPreparationTopic:
    topic_id: str
    label: str
    purpose: str
    query_terms: tuple[str, ...]
    fact_types: tuple[str, ...]


DEFAULT_MONITORING_PROTOCOL_TOPICS = (
    MonitoringProtocolPreparationTopic(
        topic_id="eligibility_continuity",
        label="入排标准与连续符合性",
        purpose=(
            "识别入选、排除、随机前复核、持续符合性和资格变化相关条款。"
        ),
        query_terms=(
            "入选标准",
            "纳入标准",
            "排除标准",
            "随机前",
            "持续符合",
            "资格",
            "inclusion",
            "exclusion",
            "eligibility",
        ),
        fact_types=("eligibility_inclusion", "eligibility_exclusion"),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="visit_window_and_order",
        label="访视计划、时间窗与顺序",
        purpose=(
            "识别计划访视、允许时间窗、访视顺序、补访和漏访相关条款。"
        ),
        query_terms=(
            "访视",
            "时间窗",
            "研究日",
            "允许范围",
            "漏访",
            "补访",
            "visit",
            "window",
            "schedule",
        ),
        fact_types=("visit_schedule", "visit_window"),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="study_treatment",
        label="试验药物方案、变更与依从性",
        purpose=(
            "识别试验药物给药方案、剂量调整、暂停、停药、重启和依从性条款；"
            "不得与非试验用合并用药混淆。"
        ),
        query_terms=(
            "试验药物",
            "研究药物",
            "给药方案",
            "剂量调整",
            "暂停给药",
            "停止给药",
            "重新给药",
            "依从性",
            "investigational product",
            "dose modification",
            "dose interruption",
            "compliance",
        ),
        fact_types=(
            "study_treatment_regimen",
            "study_treatment_change",
            "study_treatment_adherence",
        ),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="concomitant_medication_policy",
        label="合并用药政策",
        purpose=(
            "识别非试验用合并用药或治疗的允许、限制、禁用、救援和洗脱条款。"
        ),
        query_terms=(
            "合并用药",
            "伴随用药",
            "允许使用",
            "限制使用",
            "禁止使用",
            "禁用药",
            "救援治疗",
            "挽救治疗",
            "洗脱期",
            "concomitant medication",
            "prohibited medication",
            "rescue medication",
            "washout",
        ),
        fact_types=(
            "concomitant_medication_allowed",
            "concomitant_medication_restricted",
            "concomitant_medication_prohibited",
            "concomitant_medication_rescue",
            "concomitant_medication_washout",
        ),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="safety_assessment",
        label="AE、SAE、AESI 与实验室安全性",
        purpose=(
            "识别不良事件、严重不良事件、特别关注不良事件、实验室检查、"
            "临床意义和安全性随访条款。"
        ),
        query_terms=(
            "不良事件",
            "严重不良事件",
            "特别关注不良事件",
            "AESI",
            "实验室检查",
            "临床意义",
            "安全性随访",
            "adverse event",
            "serious adverse event",
            "laboratory",
            "clinically significant",
        ),
        fact_types=("safety_assessment", "aesi_definition"),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="efficacy_assessment",
        label="疗效评估",
        purpose=(
            "识别疗效终点、评价量表、评价时间点、评估者和缺失评估处理相关条款。"
        ),
        query_terms=(
            "主要终点",
            "次要终点",
            "疗效评价",
            "疗效评估",
            "评价量表",
            "评估时间",
            "endpoint",
            "efficacy",
            "assessment",
        ),
        fact_types=("efficacy_assessment",),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="early_withdrawal_and_deviation",
        label="提前退出与方案偏离",
        purpose=(
            "识别提前退出、终止研究、撤回同意、失访、方案偏离和重要方案偏离条款。"
        ),
        query_terms=(
            "提前退出",
            "退出研究",
            "终止研究",
            "撤回同意",
            "失访",
            "方案偏离",
            "方案违背",
            "重要方案偏离",
            "withdrawal",
            "discontinuation",
            "protocol deviation",
        ),
        fact_types=("early_withdrawal", "protocol_deviation"),
    ),
    MonitoringProtocolPreparationTopic(
        topic_id="data_quality",
        label="数据完整性与质量",
        purpose=(
            "识别数据完整性、一致性、源数据核对、缺失数据、重复记录和更正要求。"
        ),
        query_terms=(
            "数据完整性",
            "数据一致性",
            "源数据",
            "数据核对",
            "缺失数据",
            "数据更正",
            "重复记录",
            "data quality",
            "source data",
            "missing data",
        ),
        fact_types=("data_quality",),
    ),
)


class MonitoringProtocolPreparationService:
    """Search confirmed protocol spans and queue product-AI clause jobs."""

    def __init__(
        self,
        *,
        protocol_repository: MonitoringProtocolRuleRepository,
        ai_repository: MonitoringAiRepository,
        ai_service: MonitoringAiService,
        source_registry: Any,
        source_packet_resolver: Callable[[str, Sequence[str]], Any],
        source_span_searcher: Callable[..., Sequence[Mapping[str, Any]]],
        source_context_expander: Callable[..., Sequence[Mapping[str, Any]]]
        | None = None,
        worker_wake: Callable[[], Any] = lambda: None,
        rule_authoring_service: MonitoringRuleAuthoringService | None = None,
        topics: Sequence[MonitoringProtocolPreparationTopic] = (
            DEFAULT_MONITORING_PROTOCOL_TOPICS
        ),
        search_limit: int = 50,
    ):
        if not 1 <= search_limit <= 200:
            raise ValueError("protocol preparation search_limit must be 1 to 200")
        topic_ids = [topic.topic_id for topic in topics]
        if not topic_ids or len(topic_ids) != len(set(topic_ids)):
            raise ValueError("protocol preparation topics must be non-empty and unique")
        self.protocol_repository = protocol_repository
        self.ai_repository = ai_repository
        self.ai_service = ai_service
        self.source_registry = source_registry
        self.source_packet_resolver = source_packet_resolver
        self.source_span_searcher = source_span_searcher
        self.source_context_expander = source_context_expander
        self.worker_wake = worker_wake
        self.rule_authoring_service = (
            rule_authoring_service
            or MonitoringRuleAuthoringService(
                repository=protocol_repository,
                lifecycle_service=None,  # type: ignore[arg-type]
                protocol_rule_service=None,  # type: ignore[arg-type]
                ai_repository=ai_repository,
                source_registry=source_registry,
            )
        )
        self.topics = tuple(topics)
        self.topic_by_id = {topic.topic_id: topic for topic in self.topics}
        self.search_limit = search_limit

    def start(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        topic_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        version = self._confirmed_version(project_id, protocol_version_id)
        selected_topics = self._select_topics(topic_ids)
        self.retire_incompatible_contracts(project_id=project_id)
        existing_job_ids = {
            job.job_id
            for job in self.ai_repository.list_jobs(
                project_id,
                task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
                business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
            )
        }
        created = 0
        retried = 0
        prepared_by_topic: dict[str, Mapping[str, Any]] = {}
        for topic in selected_topics:
            prepared = self._prepare_topic(version, topic)
            prepared_by_topic[topic.topic_id] = prepared
            if prepared["status"] == "data_gap":
                continue
            packet = prepared["packet"]
            job = self.ai_service.submit_task(
                project_id=project_id,
                task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
                input_revision=packet.input_revision,
                input_payload=self._input_payload(version, topic, prepared),
                business_key=prepared["business_key"],
            )
            if job.status in {
                MonitoringAiJobStatus.FAILED,
                MonitoringAiJobStatus.BLOCKED,
                MonitoringAiJobStatus.STALE_INPUT,
            }:
                job = self.ai_repository.retry_terminal(
                    project_id,
                    job.job_id,
                    current_input_revision_sha256=(
                        packet.input_revision.revision_sha256
                    ),
                )
                retried += 1
            if job.job_id not in existing_job_ids:
                created += 1
                existing_job_ids.add(job.job_id)
        if created or retried:
            self.worker_wake()
        return self._status_payload(
            version,
            selected_topics,
            prepared_by_topic=prepared_by_topic,
        )

    def retire_incompatible_contracts(self, *, project_id: str = "") -> int:
        """Make legacy preparation contracts unavailable without deleting audit."""

        return self.ai_repository.supersede_payload_workflows_except(
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
            current_workflow=PROTOCOL_PREPARATION_CONTRACT_VERSION,
            project_id=project_id,
            reason=(
                "方案监查准备合同已升级为 "
                f"{PROTOCOL_PREPARATION_CONTRACT_VERSION}；"
                "旧作业与候选仅保留审计，不得聚合、决定或恢复。"
            ),
        )

    def status(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        topic_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        version = self._confirmed_version(project_id, protocol_version_id)
        selected_topics = self._select_topics(topic_ids)
        return self._status_payload(version, selected_topics)

    def decide_candidate(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        candidate_id: str,
        decision: MonitoringAiCandidateStatus,
        actor: str,
        reason: str,
        expected_input_revision_sha256: str,
        expected_source_revision: str,
        proposed_fact_type: str = "",
        fact_key: str = "",
        title: str = "",
        applicability: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_decision_invalid",
                "方案条款候选只能接受或驳回。",
                http_status=422,
            )
        version = self._confirmed_version(project_id, protocol_version_id)
        frozen = self._frozen_candidate_context(
            version=version,
            candidate_id=candidate_id,
            expected_input_revision_sha256=expected_input_revision_sha256,
            expected_source_revision=expected_source_revision,
        )
        candidate = frozen["candidate"]
        confidence_summary = candidate_confidence_summary(candidate)
        if (
            decision == MonitoringAiCandidateStatus.ACCEPTED
            and candidate.status == MonitoringAiCandidateStatus.PROPOSED
            and confidence_summary["requires_additional_evidence"]
            and not str(reason or "").strip()
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_low_confidence_confirmation_required",
                "该方案候选低于工作台置信度阈值；接受前请补充原文核对、数据缺口或医学确认理由。",
                http_status=422,
            )
        fact_type = ""
        resolved_fact_key = ""
        adoption_context: dict[str, Any] = {}
        if decision == MonitoringAiCandidateStatus.ACCEPTED:
            fact_type = self._fact_type_for_decision(
                frozen["topic"],
                proposed_fact_type,
            )
            resolved_fact_key = fact_key.strip() or self._default_fact_key(
                frozen["topic"],
                candidate,
            )
            adoption_context = self._adoption_context(version, frozen)
            primary_evidence = frozen["evidence"][0]
            try:
                ProtocolFact.create(
                    project_id=project_id,
                    protocol_version_id=version.protocol_version_id,
                    fact_key=resolved_fact_key,
                    fact_type=fact_type,
                    status="ai_candidate",
                    title=title.strip() or candidate.title,
                    normalized_payload={
                        "ai_candidate": candidate.model_dump(mode="json"),
                        "adoption_context": adoption_context,
                    },
                    source_entry_id=primary_evidence.source_entry_id,
                    source_locator=primary_evidence.locator,
                    source_text=primary_evidence.quote,
                    applicability=applicability or {},
                )
            except MonitoringProtocolRuleError as exc:
                raise MonitoringProtocolPreparationError(
                    "monitoring_protocol_fact_draft_invalid",
                    str(exc),
                    http_status=422,
                ) from exc
        decision_reused = False
        if candidate.status == MonitoringAiCandidateStatus.PROPOSED:
            try:
                candidate = self.ai_repository.decide_candidate(
                    project_id,
                    candidate.candidate_id,
                    decision=decision,
                    actor=actor,
                    reason=reason,
                    current_input_revision_sha256=(
                        expected_input_revision_sha256
                    ),
                )
            except MonitoringAiStateConflictError:
                candidate = self._candidate(
                    project_id,
                    frozen["job"].job_id,
                    candidate_id,
                )
                if candidate.status != decision:
                    raise MonitoringProtocolPreparationError(
                        "monitoring_protocol_candidate_decision_conflict",
                        "候选已被其他操作更新，请刷新后重试。",
                    ) from None
                decision_reused = True
        elif candidate.status == decision:
            decision_reused = True
        else:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_decision_conflict",
                "候选已记录另一项决定，不能覆盖原决定。",
            )

        base = {
            "project_id": project_id,
            "protocol_version_id": version.protocol_version_id,
            "topic_id": frozen["topic"].topic_id,
            "decision": decision.value,
            "decision_reused": decision_reused,
            "candidate": self._public_candidate(candidate),
            "source_snapshot": self._public_source_snapshot(
                version,
                frozen,
            ),
        }
        if decision == MonitoringAiCandidateStatus.REJECTED:
            return {
                **base,
                "outcome": {
                    "state": "user_rejected",
                    "fact": None,
                    "next_action": {
                        "code": "review_next_candidate",
                        "message": "该候选已驳回，可继续审核本主题其他候选。",
                    },
                },
            }

        try:
            fact, fact_reused = self.rule_authoring_service.adopt_ai_candidate(
                project_id=project_id,
                protocol_version_id=version.protocol_version_id,
                candidate_id=candidate.candidate_id,
                fact_key=resolved_fact_key,
                proposed_fact_type=fact_type,
                title=title,
                applicability=applicability,
                adoption_context=adoption_context,
            )
        except MonitoringRuleAuthoringError as exc:
            raise MonitoringProtocolPreparationError(
                exc.code,
                exc.message,
                http_status=exc.http_status,
            ) from exc
        except (
            MonitoringProtocolStateConflictError,
            ProtocolVersionConflictError,
        ) as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_fact_projection_conflict",
                "候选决定已记录，但方案事实草稿写入发生并发冲突；请刷新后重试。",
            ) from exc
        return {
            **base,
            "outcome": {
                "state": "user_confirmed_fact_draft",
                "fact": fact.public_dict(),
                "fact_reused": fact_reused,
                "next_action": {
                    "code": "review_rule_template_and_compile",
                    "message": (
                        "候选接受已构成医学经理决定；下一步仅需审阅确定性规则模板，"
                        "不会再次批准同一候选。"
                    ),
                    "endpoint": (
                        f"/api/projects/{project_id}/modules/medical-monitoring/"
                        f"protocol-facts/{fact.fact_revision_id}/confirm"
                    ),
                    "then": [
                        "create_rule_pack_draft",
                        "confirm_rule",
                        "shadow_validation",
                        "publish_rule_pack",
                    ],
                },
            },
        }

    def _frozen_candidate_context(
        self,
        *,
        version: ProtocolSourceVersion,
        candidate_id: str,
        expected_input_revision_sha256: str,
        expected_source_revision: str,
    ) -> dict[str, Any]:
        expected_input = (
            expected_input_revision_sha256
            if isinstance(expected_input_revision_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_input_revision_sha256)
            else ""
        )
        expected_source = str(expected_source_revision or "").strip()
        try:
            job = self.ai_repository.job_for_candidate(
                version.project_id,
                candidate_id,
            )
            input_payload = self.ai_repository.input_payload(
                version.project_id,
                job.job_id,
            )
        except MonitoringAiRepositoryError as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_not_found",
                "当前项目未找到该方案条款候选。",
                http_status=404,
            ) from exc
        if (
            job.status != MonitoringAiJobStatus.COMPLETED
            or job.task_type
            != MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_not_ready",
                "只有已完成的方案条款结构化候选可以接受或驳回。",
            )
        context = input_payload.get("context")
        evidence_packet = input_payload.get("evidence_packet")
        if not isinstance(context, Mapping) or not isinstance(
            evidence_packet,
            list,
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_lineage_missing",
                "候选缺少冻结的方案准备来源上下文。",
            )
        topic_id = str(context.get("topic_id") or "").strip()
        topic = self.topic_by_id.get(topic_id)
        source_revision = str(context.get("source_revision") or "").strip()
        if (
            context.get("workflow") != PROTOCOL_PREPARATION_CONTRACT_VERSION
            or context.get("protocol_version_id")
            != version.protocol_version_id
            or topic is None
            or not source_revision
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_lineage_mismatch",
                "该候选不属于当前方案版本的方案监查准备流程。",
            )
        if (
            expected_input != job.input_revision_sha256
            or expected_source != source_revision
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_source_stale",
                "候选输入或方案来源修订已变化，请刷新后重新审核。",
            )
        candidate = self._candidate(
            version.project_id,
            job.job_id,
            candidate_id,
        )
        if (
            candidate.task_type
            != MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
            or candidate.input_revision_sha256 != job.input_revision_sha256
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_lineage_mismatch",
                "候选与冻结的方案准备作业版本不一致。",
            )
        evidence = self._validate_frozen_candidate_evidence(
            version,
            candidate,
            evidence_packet,
        )
        candidate_snapshot = candidate.model_dump(mode="json")
        candidate_snapshot.pop("status", None)
        return {
            "job": job,
            "candidate": candidate,
            "topic": topic,
            "source_revision": source_revision,
            "evidence": evidence,
            "candidate_snapshot_sha256": content_sha256(candidate_snapshot),
        }

    def _candidate(
        self,
        project_id: str,
        job_id: str,
        candidate_id: str,
    ) -> MonitoringAiCandidate:
        candidate = next(
            (
                item
                for item in self.ai_repository.candidates(project_id, job_id)
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_candidate_not_found",
                "当前项目未找到该方案条款候选。",
                http_status=404,
            )
        return candidate

    @staticmethod
    def _validate_frozen_candidate_evidence(
        version: ProtocolSourceVersion,
        candidate: MonitoringAiCandidate,
        evidence_packet: Sequence[Mapping[str, Any]],
    ) -> tuple[MonitoringAiEvidence, ...]:
        packet_by_id = {
            str(item.get("evidence_id") or "").strip(): item
            for item in evidence_packet
            if isinstance(item, Mapping)
            and str(item.get("evidence_id") or "").strip()
        }
        if not candidate.evidence:
            raise MonitoringProtocolPreparationError(
                "monitoring_candidate_original_quote_missing",
                "候选未绑定真实方案原文，不能记录用户决定。",
            )
        for evidence in candidate.evidence:
            frozen = packet_by_id.get(evidence.evidence_id)
            if (
                frozen is None
                or evidence.source_entry_id != version.source_entry_id
                or evidence.source_content_sha256 != version.content_sha256
                or str(frozen.get("source_entry_id") or "").strip()
                != evidence.source_entry_id
                or not isinstance(frozen.get("source_content_sha256"), str)
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    frozen.get("source_content_sha256"),
                )
                or frozen.get("source_content_sha256")
                != evidence.source_content_sha256
                or str(frozen.get("locator") or "").strip()
                != evidence.locator.strip()
                or str(frozen.get("quote") or "").strip()
                != evidence.quote.strip()
                or not evidence.locator.strip()
                or not evidence.quote.strip()
            ):
                raise MonitoringProtocolPreparationError(
                    "monitoring_protocol_candidate_evidence_drift",
                    "候选证据与冻结方案原文、定位或内容版本不一致。",
                )
        return candidate.evidence

    @staticmethod
    def _public_source_snapshot(
        version: ProtocolSourceVersion,
        frozen: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "protocol_version_id": version.protocol_version_id,
            "protocol_version_label": version.version_label,
            "source_entry_id": version.source_entry_id,
            "source_content_sha256": version.content_sha256,
            "source_revision": frozen["source_revision"],
            "candidate_input_revision_sha256": frozen[
                "job"
            ].input_revision_sha256,
            "candidate_snapshot_sha256": frozen[
                "candidate_snapshot_sha256"
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "source_entry_id": item.source_entry_id,
                    "source_content_sha256": item.source_content_sha256,
                    "locator": item.locator,
                    "quote": item.quote,
                }
                for item in frozen["evidence"]
            ],
        }

    @staticmethod
    def _adoption_context(
        version: ProtocolSourceVersion,
        frozen: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "workflow": PROTOCOL_PREPARATION_CONTRACT_VERSION,
            "topic_id": frozen["topic"].topic_id,
            "source_revision": frozen["source_revision"],
            "protocol_version_id": version.protocol_version_id,
            "protocol_version_label": version.version_label,
            "source_entry_id": version.source_entry_id,
            "source_content_sha256": version.content_sha256,
            "candidate_input_revision_sha256": frozen[
                "candidate"
            ].input_revision_sha256,
            "candidate_snapshot_sha256": frozen[
                "candidate_snapshot_sha256"
            ],
            "evidence_source_types": ["project_protocol_original"],
            "fact_adoption_status": "adopted_as_project_fact_draft",
            "adoption_basis": "medical_manager_explicit_selection",
        }

    @staticmethod
    def _fact_type_for_decision(
        topic: MonitoringProtocolPreparationTopic,
        proposed_fact_type: str,
    ) -> str:
        selected = str(proposed_fact_type or "").strip()
        if selected:
            if selected not in topic.fact_types:
                raise MonitoringProtocolPreparationError(
                    "monitoring_protocol_fact_type_invalid",
                    "所选方案事实类型不属于该监查主题。",
                    http_status=422,
                )
            return selected
        if len(topic.fact_types) == 1:
            return topic.fact_types[0]
        raise MonitoringProtocolPreparationError(
            "monitoring_protocol_fact_type_required",
            "该主题包含多种方案事实类型，请选择与候选含义一致的类型。",
            http_status=422,
        )

    @staticmethod
    def _default_fact_key(
        topic: MonitoringProtocolPreparationTopic,
        candidate: MonitoringAiCandidate,
    ) -> str:
        digest = content_sha256(
            {
                "topic_id": topic.topic_id,
                "candidate_id": candidate.candidate_id,
            }
        )
        return f"protocol_clause.{topic.topic_id}.{digest[:16]}"

    def _status_payload(
        self,
        version: ProtocolSourceVersion,
        selected_topics: Sequence[MonitoringProtocolPreparationTopic],
        *,
        prepared_by_topic: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        items = [
            self._topic_status(
                version,
                topic,
                prepared=(
                    prepared_by_topic.get(topic.topic_id)
                    if prepared_by_topic is not None
                    else None
                ),
            )
            for topic in selected_topics
        ]
        progress = {
            "total": len(items),
            "ready": sum(item["status"] == "ready" for item in items),
            "queued": sum(item["status"] == "queued" for item in items),
            "running": sum(item["status"] == "running" for item in items),
            "candidate_review": sum(
                item["status"] == "candidate_review" for item in items
            ),
            "reviewed": sum(item["status"] == "reviewed" for item in items),
            "failed": sum(
                item["status"]
                in {"failed", "blocked", "stale_input", "cancelled"}
                for item in items
            ),
            "data_gap": sum(item["status"] == "data_gap" for item in items),
        }
        return {
            "project_id": version.project_id,
            "protocol_version_id": version.protocol_version_id,
            "protocol_version_label": version.version_label,
            "source_entry_id": version.source_entry_id,
            "status": self._overall_status(items),
            "progress": progress,
            "topics": items,
        }

    def _topic_status(
        self,
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
        *,
        prepared: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = (
            prepared
            or self._prepared_from_existing_job(version, topic)
            or self._prepare_topic(version, topic)
        )
        base = {
            "topic_id": topic.topic_id,
            "label": topic.label,
            "allowed_fact_types": list(topic.fact_types),
            "source_span_count": prepared["source_span_count"],
            "source_revision": prepared["source_revision"],
        }
        if prepared["status"] == "data_gap":
            return {
                **base,
                "status": "data_gap",
                "execution_status": "skipped",
                "reason_code": "data_gap",
                "data_gap": (
                    "当前已确认方案版本未检索到该主题的可用原文 span；"
                    "未提交 AI 作业，也未补造方案条款。"
                ),
                "job": None,
                "candidates": [],
            }

        jobs = self._matching_jobs(version, topic, prepared)
        if not jobs:
            return {
                **base,
                "status": "ready",
                "execution_status": "not_submitted",
                "reason_code": "",
                "data_gap": "",
                "job": None,
                "candidates": [],
            }
        job = jobs[-1]
        candidates = (
            self.ai_repository.candidates(version.project_id, job.job_id)
            if job.status == MonitoringAiJobStatus.COMPLETED
            else ()
        )
        public_candidates = [
            self._public_candidate(candidate) for candidate in candidates
        ]
        fact_by_candidate = self._fact_projection_by_candidate(
            version.protocol_version_id
        )
        for candidate in public_candidates:
            candidate["fact"] = fact_by_candidate.get(
                candidate["candidate_id"]
            )
        status = job.status.value
        if job.status == MonitoringAiJobStatus.COMPLETED:
            status = (
                "candidate_review"
                if any(
                    candidate.status == MonitoringAiCandidateStatus.PROPOSED
                    for candidate in candidates
                )
                else "reviewed"
            )
        return {
            **base,
            "status": status,
            "execution_status": "submitted",
            "reason_code": "",
            "data_gap": "",
            "job": self._public_job(job),
            "candidates": public_candidates,
        }

    def _fact_projection_by_candidate(
        self,
        protocol_version_id: str,
    ) -> dict[str, dict[str, Any]]:
        status_priority = {
            "ai_candidate": 1,
            "superseded": 2,
            "medically_confirmed": 3,
        }
        projected: dict[str, tuple[int, int, dict[str, Any]]] = {}
        for fact in self.protocol_repository.facts_for_version(
            protocol_version_id
        ):
            payload = fact.normalized_payload
            candidate = (
                payload.get("ai_candidate")
                if isinstance(payload, Mapping)
                else None
            )
            candidate_id = (
                str(candidate.get("candidate_id") or "").strip()
                if isinstance(candidate, Mapping)
                else ""
            )
            if not candidate_id:
                continue
            item = {
                "fact_revision_id": fact.fact_revision_id,
                "state_version": fact.state_version,
                "status": fact.status,
                "fact_type": fact.fact_type,
                "title": fact.title,
            }
            rank = (
                status_priority.get(fact.status, 0),
                int(fact.state_version),
                item,
            )
            prior = projected.get(candidate_id)
            if prior is None or rank[:2] > prior[:2]:
                projected[candidate_id] = rank
        return {
            candidate_id: value[2]
            for candidate_id, value in projected.items()
        }

    def _prepared_from_existing_job(
        self,
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
    ) -> Mapping[str, Any] | None:
        """Build a compact status snapshot without rescanning immutable spans."""

        prompt_version = PROMPT_VERSION_BY_TASK[
            MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ]
        matches: list[tuple[MonitoringAiJob, Mapping[str, Any]]] = []
        for job in self.ai_repository.list_jobs(
            version.project_id,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
            business_key_prefix=(
                f"{PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX}{topic.topic_id}:"
            ),
        ):
            if not self._prompt_version_is_status_compatible(
                job,
                prompt_version,
            ):
                continue
            try:
                payload = self.ai_repository.input_payload(
                    version.project_id,
                    job.job_id,
                )
            except MonitoringAiRepositoryError:
                continue
            context = payload.get("context")
            evidence_packet = payload.get("evidence_packet")
            if not isinstance(context, dict) or not isinstance(
                evidence_packet,
                list,
            ):
                continue
            if (
                context.get("workflow")
                != PROTOCOL_PREPARATION_CONTRACT_VERSION
                or context.get("protocol_version_id")
                != version.protocol_version_id
                or context.get("topic_id") != topic.topic_id
                or not self._job_revision_hash_is_compatible(job)
            ):
                continue
            source_revision = str(
                context.get("source_revision") or ""
            ).strip()
            if not source_revision:
                continue
            matches.append((job, payload))
        if not matches:
            return None
        job, payload = matches[-1]
        context = payload["context"]
        source_ids = tuple(
            str(item).strip()
            for item in payload.get("source_ids") or ()
            if str(item).strip()
        )
        return {
            "status": "ready",
            "source_span_count": len(payload["evidence_packet"]),
            "source_revision": context["source_revision"],
            "source_ids": source_ids,
            "business_key": job.business_key,
        }

    def _prepare_topic(
        self,
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
    ) -> dict[str, Any]:
        try:
            raw_spans = self.source_span_searcher(
                version.project_id,
                version.source_entry_id,
                topic.query_terms,
                limit=self.search_limit,
            )
        except KeyError as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_not_found",
                "当前项目未找到该方案版本对应的已登记来源。",
                http_status=404,
            ) from exc
        except ValueError as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_unusable",
                str(exc),
            ) from exc

        matched_spans = self._deduplicate_spans(raw_spans)
        if self.source_context_expander is not None and matched_spans:
            try:
                expanded_spans = self.source_context_expander(
                    version.project_id,
                    version.source_entry_id,
                    matched_spans,
                    limit=MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS,
                )
            except (KeyError, ValueError) as exc:
                raise MonitoringProtocolPreparationError(
                    "monitoring_protocol_source_context_invalid",
                    str(exc),
                ) from exc
            spans = self._deduplicate_spans(expanded_spans)
        else:
            spans = tuple(
                self._with_default_evidence_context(item)
                for item in matched_spans
            )
        spans = self._apply_topic_domain_gate(topic, spans)
        source_revision = self._source_revision(version, topic, spans)
        if not self._has_eligible_primary_match(spans):
            return {
                "status": "data_gap",
                "source_span_count": 0,
                "source_revision": source_revision,
                "source_ids": (),
                "business_key": self._business_key(
                    version,
                    topic,
                    source_revision,
                ),
            }
        source_ids = tuple(str(item["source_id"]).strip() for item in spans)
        try:
            packet = self.source_packet_resolver(version.project_id, source_ids)
        except (KeyError, ValueError) as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_packet_invalid",
                str(exc),
            ) from exc
        self._validate_packet(version, packet)
        return {
            "status": "ready",
            "source_span_count": len(spans),
            "source_revision": source_revision,
            "source_ids": source_ids,
            "spans": spans,
            "packet": packet,
            "business_key": self._business_key(
                version,
                topic,
                source_revision,
            ),
        }

    def _matching_jobs(
        self,
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
        prepared: Mapping[str, Any],
    ) -> tuple[MonitoringAiJob, ...]:
        prompt_version = PROMPT_VERSION_BY_TASK[
            MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ]
        matches = []
        for job in self.ai_repository.list_jobs(
            version.project_id,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
            business_key_prefix=str(prepared["business_key"]),
        ):
            if (
                job.business_key != prepared["business_key"]
                or not self._prompt_version_is_status_compatible(
                    job,
                    prompt_version,
                )
                or not self._job_revision_hash_is_compatible(job)
            ):
                continue
            try:
                payload = self.ai_repository.input_payload(
                    version.project_id,
                    job.job_id,
                )
            except MonitoringAiRepositoryError:
                continue
            context = payload.get("context")
            if not isinstance(context, dict):
                continue
            if (
                context.get("workflow")
                == PROTOCOL_PREPARATION_CONTRACT_VERSION
                and context.get("protocol_version_id")
                == version.protocol_version_id
                and context.get("topic_id") == topic.topic_id
                and context.get("source_revision")
                == prepared["source_revision"]
            ):
                matches.append(job)
        return tuple(matches)

    @staticmethod
    def _job_revision_hash_is_compatible(job: MonitoringAiJob) -> bool:
        """Exclude rows persisted with an obsolete revision-hash algorithm."""

        return (
            job.input_revision.revision_sha256
            == job.input_revision_sha256
        )

    @staticmethod
    def _prompt_version_is_status_compatible(
        job: MonitoringAiJob,
        current_prompt_version: str,
    ) -> bool:
        if job.prompt_version == current_prompt_version:
            return True
        return (
            job.prompt_version in PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
            and job.status
            in {
                MonitoringAiJobStatus.COMPLETED,
                MonitoringAiJobStatus.FAILED,
            }
        )

    @staticmethod
    def _deduplicate_spans(
        spans: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        result = []
        seen_source_ids: set[str] = set()
        seen_content: set[tuple[str, str, str]] = set()
        for raw in spans:
            item = dict(raw)
            source_id = str(item.get("source_id") or "").strip()
            entry_id = str(item.get("source_entry_id") or "").strip()
            locator = str(item.get("locator") or "").strip()
            text = " ".join(str(item.get("text") or "").split())
            if not source_id or not entry_id or not locator or not text:
                continue
            content_key = (entry_id, locator, text)
            if source_id in seen_source_ids or content_key in seen_content:
                continue
            seen_source_ids.add(source_id)
            seen_content.add(content_key)
            item["source_id"] = source_id
            item["source_entry_id"] = entry_id
            item["locator"] = locator
            item["text"] = text
            result.append(item)
        return tuple(result)

    @staticmethod
    def _with_default_evidence_context(
        span: Mapping[str, Any],
    ) -> dict[str, Any]:
        item = dict(span)
        context = dict(item.get("evidence_context") or {})
        context.setdefault("packet_version", PROTOCOL_EVIDENCE_PACKET_VERSION)
        context["primary_match"] = _strict_evidence_bool(
            context.get("primary_match"),
            "primary_match",
            default=True,
        )
        if "eligible_for_rule_fact" in context:
            context["eligible_for_rule_fact"] = _strict_evidence_bool(
                context.get("eligible_for_rule_fact"),
                "eligible_for_rule_fact",
                default=True,
            )
        context.setdefault("roles", ["primary_match"])
        context.setdefault("parent_match_source_ids", [item["source_id"]])
        context.setdefault(
            "structure",
            {
                "kind": (
                    "table_cell"
                    if str(item.get("locator") or "").startswith("docx:table:")
                    else "paragraph"
                )
            },
        )
        item["evidence_context"] = context
        return item

    @classmethod
    def _apply_topic_domain_gate(
        cls,
        topic: MonitoringProtocolPreparationTopic,
        spans: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        result = []
        for raw in spans:
            item = cls._with_default_evidence_context(raw)
            context = dict(item["evidence_context"])
            text = str(item.get("text") or "")
            if (
                topic.topic_id == "eligibility_continuity"
                and _ESTIMAND_MARKERS.search(text)
                and not _ELIGIBILITY_MARKERS.search(text)
            ):
                context["domain_gate"] = (
                    "context_only_estimand_target_population"
                )
                context["eligible_for_rule_fact"] = False
            else:
                context["domain_gate"] = "topic_eligible"
                context["eligible_for_rule_fact"] = True
            item["evidence_context"] = context
            result.append(item)
        return tuple(result)

    @staticmethod
    def _has_eligible_primary_match(
        spans: Sequence[Mapping[str, Any]],
    ) -> bool:
        return any(
            _strict_evidence_bool(
                (item.get("evidence_context") or {}).get("primary_match"),
                "primary_match",
                default=False,
            )
            and _strict_evidence_bool(
                (item.get("evidence_context") or {}).get(
                    "eligible_for_rule_fact"
                ),
                "eligible_for_rule_fact",
                default=True,
            )
            for item in spans
        )

    @staticmethod
    def _validate_packet(version: ProtocolSourceVersion, packet: Any) -> None:
        sources = tuple(packet.input_revision.sources)
        if len(sources) != 1:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_revision_mismatch",
                "方案监查准备要求所有证据 span 来自同一已确认方案版本。",
            )
        source = sources[0]
        if (
            source.source_entry_id != version.source_entry_id
            or source.source_content_sha256 != version.content_sha256
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_revision_mismatch",
                "已登记方案版本与当前真实 span 的来源或内容版本不一致。",
            )

    def _confirmed_version(
        self,
        project_id: str,
        protocol_version_id: str,
    ) -> ProtocolSourceVersion:
        try:
            version = self.protocol_repository.protocol_version(
                protocol_version_id
            )
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            ) from exc
        if version.project_id != project_id:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            )
        if version.status != "confirmed":
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_version_not_confirmed",
                "只有已确认的方案版本可以启动方案监查准备。",
            )
        self._validate_registered_source(version)
        return version

    def _validate_registered_source(
        self,
        version: ProtocolSourceVersion,
    ) -> None:
        entry = next(
            (
                item
                for item in self.source_registry.list_entries(version.project_id)
                if item.entry_id == version.source_entry_id
            ),
            None,
        )
        if entry is None:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_not_found",
                "当前项目未找到该方案版本对应的已登记来源。",
                http_status=404,
            )
        if (
            entry.module != "medical_monitoring"
            or entry.source_kind != "protocol_docx"
            or entry.content_hash != version.content_sha256
        ):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_revision_mismatch",
                "已确认方案版本与医学监查来源登记不一致。",
            )
        if entry.parser_status != "parsed" or int(entry.span_count or 0) < 1:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_source_not_parsed",
                "方案来源尚未完成可用文本 span 解析，不能启动方案监查准备。",
            )

    def _select_topics(
        self,
        topic_ids: Sequence[str],
    ) -> tuple[MonitoringProtocolPreparationTopic, ...]:
        cleaned = tuple(dict.fromkeys(str(item).strip() for item in topic_ids))
        if any(not item for item in cleaned):
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_topic_invalid",
                "方案监查准备主题不能为空。",
                http_status=422,
            )
        if not cleaned:
            return self.topics
        unknown = [item for item in cleaned if item not in self.topic_by_id]
        if unknown:
            raise MonitoringProtocolPreparationError(
                "monitoring_protocol_topic_invalid",
                "未知的方案监查准备主题：" + "、".join(unknown),
                http_status=422,
            )
        return tuple(self.topic_by_id[item] for item in cleaned)

    @staticmethod
    def _source_revision(
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
        spans: Sequence[Mapping[str, Any]],
    ) -> str:
        digest = content_sha256(
            {
                "contract_version": PROTOCOL_PREPARATION_CONTRACT_VERSION,
                "protocol_version_id": version.protocol_version_id,
                "source_entry_id": version.source_entry_id,
                "source_content_sha256": version.content_sha256,
                "topic_id": topic.topic_id,
                "query_terms": list(topic.query_terms),
                "spans": [
                    {
                        "source_id": item["source_id"],
                        "locator": item["locator"],
                        "text": item["text"],
                        "evidence_context": item.get("evidence_context") or {},
                    }
                    for item in spans
                ],
            }
        )
        return f"mpr_{digest[:28]}"

    @staticmethod
    def _business_key(
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
        source_revision: str,
    ) -> str:
        identity = content_sha256(
            {
                "protocol_version_id": version.protocol_version_id,
                "topic_id": topic.topic_id,
                "source_revision": source_revision,
            }
        )
        return (
            f"{PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX}"
            f"{topic.topic_id}:{identity[:32]}"
        )

    @staticmethod
    def _input_payload(
        version: ProtocolSourceVersion,
        topic: MonitoringProtocolPreparationTopic,
        prepared: Mapping[str, Any],
    ) -> dict[str, Any]:
        packet = prepared["packet"]
        span_by_source_id = {
            str(item["source_id"]).strip(): item
            for item in prepared["spans"]
        }
        evidence_packet = []
        for raw in packet.evidence_packet:
            item = dict(raw)
            raw_fields = dict(item.get("raw_fields") or {})
            source_id = str(raw_fields.get("source_id") or "").strip()
            span = span_by_source_id.get(source_id)
            if span is not None:
                raw_fields["protocol_context"] = dict(
                    span.get("evidence_context") or {}
                )
            item["raw_fields"] = raw_fields
            evidence_packet.append(item)
        source_conflicts = _detect_source_conflicts(
            evidence_packet,
            topic_id=topic.topic_id,
        )
        return {
            "context": {
                "workflow": PROTOCOL_PREPARATION_CONTRACT_VERSION,
                "evidence_packet_version": PROTOCOL_EVIDENCE_PACKET_VERSION,
                "protocol_version_id": version.protocol_version_id,
                "protocol_code": version.protocol_code,
                "protocol_version_label": version.version_label,
                "topic_id": topic.topic_id,
                "topic_label": topic.label,
                "purpose": topic.purpose,
                "candidate_fact_types": list(topic.fact_types),
                "source_revision": prepared["source_revision"],
                "retrieval_scope": "bounded_structural_context",
                "absence_assertion_authority": "none",
                "detected_source_conflicts": source_conflicts,
                "domain_gate": {
                    "estimand_target_population_is_not_eligibility": True,
                    "context_only_evidence_cannot_support_rule_fact": True,
                },
                "medication_boundary": {
                    "cm": "non_investigational_medication_or_treatment_only",
                    "ip": (
                        "investigational_product_administration_dose_change_"
                        "interruption_restart_discontinuation"
                    ),
                },
                "instruction": (
                    "仅结构化本证据包中的方案原文及结构化邻接语境。"
                    "按独立条款拆分候选，"
                    "保留适用对象、条件、时间窗、阈值、例外和动作；"
                    "表格证据必须将同行条件、阈值和动作作为整体解释；"
                    "连续列表必须保留列表标题和条目层级。"
                    "不得补造未出现的要求。当前证据包未检索到的内容只能"
                    "标记为检索缺口，不能声称方案未规定。检测到原文冲突时"
                    "必须并列保留并要求用户裁决，禁止静默选择。"
                ),
            },
            "source_ids": list(packet.source_ids),
            "evidence_packet": evidence_packet,
        }

    @staticmethod
    def _public_job(job: MonitoringAiJob) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "attempt_count": job.attempt_count,
            "failure_code": job.failure_code,
            "failure_message": job.failure_message,
            "updated_at": job.updated_at.isoformat(),
        }

    @staticmethod
    def _public_candidate(candidate: MonitoringAiCandidate) -> dict[str, Any]:
        review_status = {
            MonitoringAiCandidateStatus.PROPOSED: "pending_user_confirmation",
            MonitoringAiCandidateStatus.ACCEPTED: "user_confirmed",
            MonitoringAiCandidateStatus.REJECTED: "user_rejected",
            MonitoringAiCandidateStatus.SUPERSEDED: "superseded",
        }[candidate.status]
        referenced_evidence_ids = {
            str(item).strip()
            for item in (
                list(
                    candidate.structured_payload.get("evidence_ids") or ()
                )
                + [
                    evidence_id
                    for claim in candidate.claims
                    for evidence_id in claim.evidence_ids
                ]
            )
            if str(item).strip()
        }
        return {
            "candidate_id": candidate.candidate_id,
            "status": candidate.status.value,
            "review_status": review_status,
            "title": candidate.title,
            "text": candidate.text,
            "structured_payload": candidate.structured_payload,
            "claims": [
                {
                    "kind": claim.kind.value,
                    "text": claim.text,
                    "confidence": claim.confidence,
                    "uncertainty": claim.uncertainty,
                    "user_action": claim.user_action,
                    "evidence_ids": list(claim.evidence_ids),
                }
                for claim in candidate.claims
            ],
            "evidence": [
                {
                    "evidence_id": evidence.evidence_id,
                    "source_entry_id": evidence.source_entry_id,
                    "locator": evidence.locator,
                    "quote": evidence.quote,
                }
                for evidence in candidate.evidence
                if evidence.evidence_id in referenced_evidence_ids
            ],
            "confidence_summary": candidate_confidence_summary(candidate),
        }

    @staticmethod
    def _overall_status(items: Sequence[Mapping[str, Any]]) -> str:
        statuses = {str(item["status"]) for item in items}
        if statuses.intersection(
            {"failed", "blocked", "stale_input", "cancelled"}
        ):
            return "attention_required"
        if statuses.intersection({"queued", "running"}):
            return "in_progress"
        if "candidate_review" in statuses:
            return "candidate_review"
        if statuses == {"data_gap"}:
            return "data_gap"
        if statuses and statuses.issubset({"reviewed", "data_gap"}):
            return "reviewed"
        return "ready"


def _detect_source_conflicts(
    evidence_packet: Sequence[Mapping[str, Any]],
    *,
    topic_id: str = "",
) -> list[dict[str, Any]]:
    """Detect topic-scoped medication-action source conflicts only.

    Medication-action conflicts are injected only for the exact topic/object
    pair: study-treatment jobs may receive only investigational-product
    conflicts and concomitant-medication jobs only
    ``concomitant_non_investigational`` conflicts. Every other topic
    (including the visit topic) gets no conflicts, so a visit job is never
    forced to emit an IP stop conflict merely because a visit word occurs in
    its source, and a CM job never carries an IP conflict or vice versa.
    """

    allowed_object_scope = {
        "study_treatment": "investigational_product",
        "concomitant_medication_policy": "concomitant_non_investigational",
    }.get(topic_id)
    if allowed_object_scope is None:
        return []
    observations: dict[
        tuple[str, str, str],
        dict[str, dict[str, set[str]]],
    ] = {}
    for evidence in evidence_packet:
        evidence_id = str(evidence.get("evidence_id") or "").strip()
        quote = str(evidence.get("quote") or "").strip()
        if not evidence_id or not quote:
            continue
        for sentence in re.split(r"(?<=[。；;])|\n+", quote):
            cleaned = " ".join(sentence.split())
            if not cleaned:
                continue
            action_match = _source_action(cleaned)
            if action_match is None:
                continue
            action, action_start = action_match
            modality = _source_modality(cleaned, action_start)
            if modality is None:
                continue
            object_scope = _source_object_scope(cleaned)
            condition_scope = _source_condition_scope(cleaned, action_start)
            key = (object_scope, action, condition_scope)
            by_modality = observations.setdefault(key, {})
            bucket = by_modality.setdefault(
                modality,
                {"evidence_ids": set(), "quotes": set()},
            )
            bucket["evidence_ids"].add(evidence_id)
            bucket["quotes"].add(cleaned)

    conflicts = []
    for (
        object_scope,
        action,
        condition_scope,
    ), by_modality in sorted(observations.items()):
        if object_scope != allowed_object_scope:
            continue
        modalities = sorted(by_modality)
        if len(modalities) < 2:
            continue
        evidence_ids = sorted(
            {
                evidence_id
                for bucket in by_modality.values()
                for evidence_id in bucket["evidence_ids"]
            }
        )
        if len(evidence_ids) < 2:
            continue
        conflict_seed = {
            "object_scope": object_scope,
            "action": action,
            "condition_scope": condition_scope,
            "modalities": modalities,
            "evidence_ids": evidence_ids,
        }
        conflicts.append(
            {
                "conflict_id": "protocol_conflict_"
                + content_sha256(conflict_seed)[:20],
                "object_scope": object_scope,
                "action": action,
                "condition_scope": condition_scope,
                "modalities": modalities,
                "status": "requires_user_resolution",
                "evidence_ids": evidence_ids,
                "source_variants": [
                    {
                        "modality": modality,
                        "quotes": sorted(by_modality[modality]["quotes"]),
                        "evidence_ids": sorted(
                            by_modality[modality]["evidence_ids"]
                        ),
                    }
                    for modality in modalities
                ],
            }
        )
    return conflicts


def _source_modality(text: str, action_start: int) -> str | None:
    nearest = _nearest_modality_match(text, action_start)
    return nearest[1] if nearest is not None else None


def _nearest_modality_match(
    text: str,
    action_start: int,
) -> tuple[int, str, Any] | None:
    matches = [
        (action_start - match.end(), modality, match)
        for modality, pattern in _MODALITY_PATTERNS
        for match in pattern.finditer(text)
        if 0 <= action_start - match.end() <= 12
    ]
    return min(matches, key=lambda item: item[:2]) if matches else None


def _source_condition_scope(text: str, action_start: int) -> str:
    nearest = _nearest_modality_match(text, action_start)
    prefix = text[: nearest[2].start() if nearest is not None else action_start]
    prefix = re.sub(r"(?:受试者|患者|研究对象)\s*$", "", prefix)
    normalized = re.sub(r"[\s，,。；;：:（）()]+", "", prefix)
    return normalized[-120:] or "unspecified_condition"


def _source_action(text: str) -> tuple[str, int] | None:
    matches = [
        (match.start(), action)
        for action, pattern in _ACTION_PATTERNS
        for match in pattern.finditer(text)
    ]
    if not matches:
        return None
    start, action = min(matches)
    return action, start


def _source_object_scope(text: str) -> str:
    if _IP_OBJECT_RE.search(text):
        return "investigational_product"
    if _CM_OBJECT_RE.search(text):
        return "concomitant_non_investigational"
    return "unspecified"
