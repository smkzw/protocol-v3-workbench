from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packages.contracts.workbench_contracts import SourceRegistrySpan

from services.api.app.ai_gateway import AiPromptEnvelope
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobCreate,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    content_sha256,
)
from services.api.app.monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiStateConflictError,
)
from services.api.app.monitoring_ai_service import (
    PROMPT_VERSION_BY_TASK,
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
)
from services.api.app.monitoring_ai_source_packet import (
    MonitoringAiSourcePacket,
    PROTOCOL_EVIDENCE_PACKET_VERSION,
    expand_protocol_evidence_spans,
)
from services.api.app.monitoring_protocol_preparation_router import (
    create_monitoring_protocol_preparation_router,
)
from services.api.app.monitoring_protocol_preparation_service import (
    DEFAULT_MONITORING_PROTOCOL_TOPICS,
    PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    PROTOCOL_PREPARATION_CONTRACT_VERSION,
    PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS,
    PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS,
    MonitoringProtocolPreparationError,
    MonitoringProtocolPreparationService,
    _detect_source_conflicts,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rules import ProtocolSourceVersion

PROJECT_ID = "project-protocol-preparation"
OTHER_PROJECT_ID = "project-other"
SOURCE_ENTRY_ID = "source-protocol-confirmed"
SOURCE_HASH = "a" * 64


class FakeProtocolSpanResolver:
    def __init__(
        self,
        *,
        source_hash: str = SOURCE_HASH,
        gap_topics: Sequence[str] = (),
    ):
        self.source_hash = source_hash
        self.gap_topics = set(gap_topics)
        self.search_calls: list[tuple[str, str, tuple[str, ...], int]] = []
        self.resolve_calls: list[tuple[str, tuple[str, ...]]] = []

    def search(
        self,
        project_id: str,
        entry_id: str,
        query_terms: Sequence[str],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        terms = tuple(query_terms)
        self.search_calls.append((project_id, entry_id, terms, limit))
        topic_id = self._topic_id(terms)
        if topic_id in self.gap_topics:
            return ()
        text = f"{topic_id}：方案要求按规定时间窗完成相应核对。"
        base = {
            "source_id": f"span-{topic_id}",
            "source_entry_id": SOURCE_ENTRY_ID,
            "locator": f"docx:paragraph:{topic_id}",
            "text": text,
            "score": 1001,
            "matched_keywords": [terms[0]],
            "match_reason": f"命中关键词：{terms[0]}",
        }
        return (
            base,
            dict(base),
            {
                **base,
                "source_id": f"span-duplicate-{topic_id}",
            },
        )

    def resolve(
        self,
        project_id: str,
        source_ids: Sequence[str],
    ) -> MonitoringAiSourcePacket:
        cleaned = tuple(source_ids)
        self.resolve_calls.append((project_id, cleaned))
        evidence = tuple(
            {
                "evidence_id": f"evidence-{source_id}",
                "source_entry_id": SOURCE_ENTRY_ID,
                "source_content_sha256": self.source_hash,
                "locator": f"docx:span:{source_id}",
                "quote": f"{source_id} 对应的真实方案原文。",
                "raw_fields": {
                    "source_id": source_id,
                    "source_type": "protocol_docx_paragraph",
                },
            }
            for source_id in cleaned
        )
        return MonitoringAiSourcePacket(
            input_revision=MonitoringAiInputRevision(
                project_id=project_id,
                batch_revision=f"source-registry:{self.source_hash[:24]}",
                protocol_version=f"source-revision:{self.source_hash[:24]}",
                sources=(
                    MonitoringAiSourceBinding(
                        source_entry_id=SOURCE_ENTRY_ID,
                        source_content_sha256=self.source_hash,
                    ),
                ),
            ),
            source_ids=cleaned,
            evidence_packet=evidence,
        )

    @staticmethod
    def _topic_id(terms: Sequence[str]) -> str:
        for topic in DEFAULT_MONITORING_PROTOCOL_TOPICS:
            if tuple(topic.query_terms) == tuple(terms):
                return topic.topic_id
        raise AssertionError(f"unexpected query terms: {terms}")


class MalformedEvidenceContextResolver(FakeProtocolSpanResolver):
    def __init__(self, *, field: str, value: Any):
        super().__init__()
        self.field = field
        self.value = value

    def search(
        self,
        project_id: str,
        entry_id: str,
        query_terms: Sequence[str],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        matches = super().search(
            project_id,
            entry_id,
            query_terms,
            limit=limit,
        )
        first = dict(matches[0])
        first["evidence_context"] = {self.field: self.value}
        return (first,)


class ScientificShapeProtocolSpanResolver(FakeProtocolSpanResolver):
    def __init__(
        self,
        *,
        match_ids_by_topic: dict[str, tuple[str, ...]],
    ):
        super().__init__()
        self.match_ids_by_topic = match_ids_by_topic
        now = datetime(2026, 7, 30, tzinfo=timezone.utc)

        def span(
            source_id: str,
            locator: str,
            text: str,
            source_type: str = "protocol_docx_paragraph",
        ) -> SourceRegistrySpan:
            return SourceRegistrySpan(
                source_id=source_id,
                entry_id=SOURCE_ENTRY_ID,
                project_id=PROJECT_ID,
                module="medical_monitoring",
                source_type=source_type,
                title="跨项目真实形状方案",
                locator=locator,
                text_preview=text,
                created_at=now,
            )

        self.spans = (
            span("ip-heading", "docx:paragraph:840", "试验药物暂停与停药标准"),
            span("table-caption", "docx:paragraph:841", "表4 暂停和停药标准"),
            span(
                "table-header-condition",
                "docx:table:4:row:0:cell:0:paragraph:842",
                "触发条件",
                "protocol_docx_table_cell",
            ),
            span(
                "table-header-action",
                "docx:table:4:row:0:cell:1:paragraph:843",
                "处理措施",
                "protocol_docx_table_cell",
            ),
            span(
                "table-threshold",
                "docx:table:4:row:2:cell:0:paragraph:849",
                "ALT或AST>3×ULN",
                "protocol_docx_table_cell",
            ),
            span(
                "table-action",
                "docx:table:4:row:2:cell:1:paragraph:850",
                "48小时内复查并暂停研究药物",
                "protocol_docx_table_cell",
            ),
            span(
                "ip-required",
                "docx:paragraph:887",
                "IGA为0分3天后，受试者需停用研究药物。",
            ),
            span(
                "ip-optional",
                "docx:paragraph:962",
                "IGA为0分3天后，受试者可停用研究药物。",
            ),
            span(
                "estimand-population",
                "docx:paragraph:1178",
                "主要估计目标的目标人群为所有随机化患者。",
            ),
        )
        self.span_by_id = {item.source_id: item for item in self.spans}

    def search(
        self,
        project_id: str,
        entry_id: str,
        query_terms: Sequence[str],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        terms = tuple(query_terms)
        self.search_calls.append((project_id, entry_id, terms, limit))
        topic_id = self._topic_id(terms)
        return tuple(
            {
                "source_id": source_id,
                "source_entry_id": SOURCE_ENTRY_ID,
                "locator": self.span_by_id[source_id].locator,
                "text": self.span_by_id[source_id].text_preview,
                "score": 1001,
                "matched_keywords": [terms[0]],
                "match_reason": f"命中关键词：{terms[0]}",
            }
            for source_id in self.match_ids_by_topic.get(topic_id, ())
        )

    def expand(
        self,
        project_id: str,
        entry_id: str,
        matches: Sequence[dict[str, Any]],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        return expand_protocol_evidence_spans(
            self.spans,
            matches,
            limit=limit,
        )

    def resolve(
        self,
        project_id: str,
        source_ids: Sequence[str],
    ) -> MonitoringAiSourcePacket:
        cleaned = tuple(source_ids)
        self.resolve_calls.append((project_id, cleaned))
        evidence = tuple(
            {
                "evidence_id": f"evidence-{source_id}",
                "source_entry_id": SOURCE_ENTRY_ID,
                "source_content_sha256": self.source_hash,
                "locator": self.span_by_id[source_id].locator,
                "quote": self.span_by_id[source_id].text_preview,
                "raw_fields": {
                    "source_id": source_id,
                    "source_type": self.span_by_id[source_id].source_type,
                },
            }
            for source_id in cleaned
        )
        return MonitoringAiSourcePacket(
            input_revision=MonitoringAiInputRevision(
                project_id=project_id,
                batch_revision=f"source-registry:{self.source_hash[:24]}",
                protocol_version=f"source-revision:{self.source_hash[:24]}",
                sources=(
                    MonitoringAiSourceBinding(
                        source_entry_id=SOURCE_ENTRY_ID,
                        source_content_sha256=self.source_hash,
                    ),
                ),
            ),
            source_ids=cleaned,
            evidence_packet=evidence,
        )


class FakeProductAiProvider:
    provider_name = "test-product-ai"
    model_name = "test-product-model"
    expected_response_model = "test-product-model"
    response_model = "test-product-model"
    transport_name = "openai_compatible"

    def __init__(self):
        self.run_count = 0

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        self.run_count += 1
        input_payload = envelope.payload["input_payload"]
        evidence_ids = [
            item["evidence_id"]
            for item in input_payload["evidence_packet"]
        ]
        topic_id = input_payload["context"]["topic_id"]
        candidate_fact_types = input_payload["context"].get(
            "candidate_fact_types"
        ) or ["safety_assessment"]
        return {
            "schema_version": "monitoring_ai_v1",
            "task_id": envelope.task_id,
            "task_type": "protocol_clause_structuring",
            "input_revision_sha256": envelope.payload[
                "input_revision_sha256"
            ],
            "candidates": [
                {
                    "candidate_type": "protocol_clause_structure",
                    "title": f"{topic_id} 条款结构化候选",
                    "text": "仅供用户基于原文确认。",
                    "structured_payload": {
                        "clause_id": f"clause-{topic_id}",
                        "fact_type": str(candidate_fact_types[0]).strip(),
                        "subject_scope": "方案规定的适用受试者",
                        "conditions": ["满足方案原文所述条件"],
                        "time_windows": ["按方案原文时间窗"],
                        "thresholds": [],
                        "exceptions": [],
                        "required_actions": ["由用户核对并确认结构化结果"],
                        "evidence_ids": evidence_ids,
                    },
                    "claims": [
                        {
                            "claim_id": f"claim-{topic_id}",
                            "kind": "fact",
                            "text": "方案原文包含该监查主题相关条款。",
                            "confidence": 0.9,
                            "uncertainty": "",
                            "user_action": "核对结构化字段与方案原文。",
                            "evidence_ids": evidence_ids,
                        }
                    ],
                }
            ],
        }


class FakeSourceRegistry:
    def __init__(
        self,
        *,
        parser_status: str = "parsed",
        span_count: int = 20,
        source_hash: str = SOURCE_HASH,
    ):
        self.parser_status = parser_status
        self.span_count = span_count
        self.source_hash = source_hash

    def list_entries(self, project_id: str):
        if project_id != PROJECT_ID:
            return []
        return [
            SimpleNamespace(
                entry_id=SOURCE_ENTRY_ID,
                project_id=PROJECT_ID,
                module="medical_monitoring",
                source_kind="protocol_docx",
                content_hash=self.source_hash,
                parser_status=self.parser_status,
                span_count=self.span_count,
            )
        ]


def _version(
    *,
    project_id: str = PROJECT_ID,
    status: str = "confirmed",
) -> ProtocolSourceVersion:
    return ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code="PROTO-PREP-001",
        version_label="V1.0",
        version_date="2026-07-01",
        source_entry_id=SOURCE_ENTRY_ID,
        source_title="项目研究方案 V1.0",
        content_sha256=SOURCE_HASH,
        status=status,
        applicability_status="project_effective_confirmed",
        operational_effective_from="2026-07-01",
    )


def _service(
    tmp_path: Path,
    *,
    resolver: FakeProtocolSpanResolver | None = None,
) -> tuple[
    MonitoringProtocolPreparationService,
    MonitoringAiRepository,
    MonitoringAiService,
    FakeProductAiProvider,
    ProtocolSourceVersion,
    list[str],
]:
    protocol_repository = MonitoringProtocolRuleRepository(
        tmp_path / "protocol-rules.sqlite3"
    )
    version = protocol_repository.register_protocol_version(_version())
    ai_repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    provider = FakeProductAiProvider()
    ai_service = MonitoringAiService(
        ai_repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider=provider.provider_name,
            model=provider.model_name,
            env={
                "WORKBENCH_AI_PROVIDER": provider.provider_name,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": provider.model_name,
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": provider.model_name,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: provider,
    )
    evidence_resolver = resolver or FakeProtocolSpanResolver()
    wake_events: list[str] = []
    service = MonitoringProtocolPreparationService(
        protocol_repository=protocol_repository,
        ai_repository=ai_repository,
        ai_service=ai_service,
        source_registry=FakeSourceRegistry(),
        source_packet_resolver=evidence_resolver.resolve,
        source_span_searcher=evidence_resolver.search,
        source_context_expander=getattr(
            evidence_resolver,
            "expand",
            None,
        ),
        worker_wake=lambda: wake_events.append("wake"),
    )
    return (
        service,
        ai_repository,
        ai_service,
        provider,
        version,
        wake_events,
    )


def _completed_legacy_protocol_job(
    service: MonitoringProtocolPreparationService,
    ai_service: MonitoringAiService,
    *,
    version: ProtocolSourceVersion,
    topic_id: str,
):
    topic = service.topic_by_id[topic_id]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    payload["context"] = {
        **payload["context"],
        "workflow": "monitoring_protocol_preparation_v1",
        "evidence_packet_version": "monitoring_protocol_evidence_packet_v1",
    }
    job = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=payload,
        business_key=(
            f"{PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX}{topic_id}:legacy-v1"
        ),
    )
    completed = ai_service.run_next("legacy-protocol-worker")
    assert completed.processed is True
    assert completed.job is not None
    assert completed.job.job_id == job.job_id
    return completed.job


def _queued_legacy_protocol_job(
    service: MonitoringProtocolPreparationService,
    ai_service: MonitoringAiService,
    *,
    version: ProtocolSourceVersion,
    topic_id: str,
):
    topic = service.topic_by_id[topic_id]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    payload["context"] = {
        **payload["context"],
        "workflow": "monitoring_protocol_preparation_v1",
        "evidence_packet_version": "monitoring_protocol_evidence_packet_v1",
    }
    return ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=payload,
        business_key=(
            f"{PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX}{topic_id}:legacy-v1"
        ),
    )


def test_default_topics_cover_required_monitoring_scope() -> None:
    topic_ids = {topic.topic_id for topic in DEFAULT_MONITORING_PROTOCOL_TOPICS}
    fact_types = {
        fact_type
        for topic in DEFAULT_MONITORING_PROTOCOL_TOPICS
        for fact_type in topic.fact_types
    }

    assert topic_ids == {
        "eligibility_continuity",
        "visit_window_and_order",
        "study_treatment",
        "concomitant_medication_policy",
        "safety_assessment",
        "efficacy_assessment",
        "early_withdrawal_and_deviation",
        "data_quality",
    }
    assert {
        "eligibility_inclusion",
        "eligibility_exclusion",
        "visit_schedule",
        "visit_window",
        "study_treatment_regimen",
        "study_treatment_change",
        "study_treatment_adherence",
        "concomitant_medication_allowed",
        "concomitant_medication_restricted",
        "concomitant_medication_prohibited",
        "concomitant_medication_rescue",
        "concomitant_medication_washout",
        "safety_assessment",
        "aesi_definition",
        "efficacy_assessment",
        "early_withdrawal",
        "protocol_deviation",
        "data_quality",
    }.issubset(fact_types)


def test_one_click_searches_real_spans_deduplicates_and_is_idempotent(
    tmp_path: Path,
) -> None:
    resolver = FakeProtocolSpanResolver()
    service, repository, _ai_service, _provider, version, wakes = _service(
        tmp_path,
        resolver=resolver,
    )

    first = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
    )
    search_count_after_start = len(resolver.search_calls)
    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
    )
    assert len(resolver.search_calls) == search_count_after_start
    second = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
    )

    assert first["status"] == "in_progress"
    assert first["progress"]["queued"] == len(DEFAULT_MONITORING_PROTOCOL_TOPICS)
    assert first["progress"]["data_gap"] == 0
    assert second["progress"] == first["progress"]
    assert status["progress"] == first["progress"]
    assert len(resolver.search_calls) == (
        search_count_after_start + len(DEFAULT_MONITORING_PROTOCOL_TOPICS)
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type="protocol_clause_structuring",
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    assert len(jobs) == len(DEFAULT_MONITORING_PROTOCOL_TOPICS)
    assert len({job.job_id for job in jobs}) == len(jobs)
    assert {
        job.prompt_version for job in jobs
    } == {"monitoring-protocol-clause-structuring-v12"}
    assert wakes == ["wake"]
    assert all(item["source_span_count"] == 1 for item in first["topics"])
    assert all(len(source_ids) == 1 for _project, source_ids in resolver.resolve_calls)

    payload = repository.input_payload(PROJECT_ID, jobs[0].job_id)
    context = payload["context"]
    assert context["protocol_version_id"] == version.protocol_version_id
    assert context["topic_id"]
    assert context["source_revision"].startswith("mpr_")
    assert context["workflow"] == "monitoring_protocol_preparation_v2"
    assert jobs[0].business_key.startswith(PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX)


@pytest.mark.parametrize(
    "legacy_prompt_version",
    (
        "monitoring-protocol-clause-structuring-v3",
        "monitoring-protocol-clause-structuring-v4",
        "monitoring-protocol-clause-structuring-v5",
        "monitoring-protocol-clause-structuring-v6",
        "monitoring-protocol-clause-structuring-v7",
        "monitoring-protocol-clause-structuring-v8",
    ),
)
def test_terminal_legacy_candidate_remains_visible_after_v10_prompt_cutover(
    tmp_path: Path,
    legacy_prompt_version: str,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["concomitant_medication_policy"]
    prepared = service._prepare_topic(version, topic)
    legacy = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=prepared["business_key"],
        prompt_version=legacy_prompt_version,
    )

    completed = ai_service.run_next("legacy-protocol-worker")
    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )

    assert completed.job is not None
    assert completed.job.job_id == legacy.job_id
    assert completed.job.prompt_version == legacy_prompt_version
    assert status["progress"]["candidate_review"] == 1
    assert status["topics"][0]["job"]["job_id"] == legacy.job_id
    assert len(
        repository.candidates(PROJECT_ID, legacy.job_id)
    ) == 1


def test_v7_legacy_completed_job_survives_v10_prompt_cutover_with_legacy_set(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["concomitant_medication_policy"]
    prepared = service._prepare_topic(version, topic)
    legacy = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=prepared["business_key"],
        prompt_version="monitoring-protocol-clause-structuring-v7",
    )
    completed = ai_service.run_next("legacy-protocol-worker")
    assert completed.job is not None
    assert completed.job.job_id == legacy.job_id

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version="monitoring-protocol-clause-structuring-v12",
        legacy_terminal_prompt_versions=PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS,
    )

    assert changed == 0
    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    assert status["progress"]["candidate_review"] == 1
    assert status["topics"][0]["job"]["job_id"] == legacy.job_id
    assert status["topics"][0]["candidates"][0]["status"] == "proposed"
    assert repository.candidates(PROJECT_ID, legacy.job_id)[0].status == (
        MonitoringAiCandidateStatus.PROPOSED
    )


def test_v7_queued_work_is_fail_closed_after_v12_prompt_cutover(
    tmp_path: Path,
) -> None:
    """v7 and v8 stay visible only as terminal legacy versions.

    Completed/failed v7 and v8 jobs remain status-compatible for audit and
    review; queued legacy jobs are excluded from the current contract, so
    new work is always submitted as v12 and v7/v8 (like v3-v6) are never
    reused for execution. The retired v9, v10 and v11 identities are
    deliberately absent from the status-compatible set while present in
    the retirement-audit set: terminal v9-v11 evidence survives the v12
    startup cutover intact but is never status-compatible, retryable or
    reusable under v12.
    """
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["concomitant_medication_policy"]
    prepared = service._prepare_topic(version, topic)
    current_version = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]
    assert current_version == "monitoring-protocol-clause-structuring-v12"
    assert "monitoring-protocol-clause-structuring-v10" not in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v10" in (
        PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v6" in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v7" in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v8" in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v9" not in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v9" in (
        PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v11" not in (
        PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    )
    assert "monitoring-protocol-clause-structuring-v11" in (
        PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
    )

    terminal_v9 = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=f"{prepared['business_key']}:v9-terminal",
        prompt_version="monitoring-protocol-clause-structuring-v9",
    )
    completed_v9 = ai_service.run_next("legacy-v9-worker")
    assert completed_v9.job is not None
    assert completed_v9.job.job_id == terminal_v9.job_id
    assert completed_v9.job.status == MonitoringAiJobStatus.COMPLETED
    # Preserved but retired: the completed v9 row stays queryable with its
    # candidate while it is never status-compatible under the v10 contract.
    assert (
        service._prompt_version_is_status_compatible(
            completed_v9.job,
            current_version,
        )
        is False
    )
    assert len(repository.candidates(PROJECT_ID, terminal_v9.job_id)) == 1

    terminal_v7 = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=prepared["business_key"],
        prompt_version="monitoring-protocol-clause-structuring-v7",
    )
    completed = ai_service.run_next("legacy-protocol-worker")
    assert completed.job is not None
    assert completed.job.job_id == terminal_v7.job_id
    assert (
        service._prompt_version_is_status_compatible(
            completed.job,
            current_version,
        )
        is True
    )
    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    assert status["topics"][0]["job"]["job_id"] == terminal_v7.job_id
    assert len(repository.candidates(PROJECT_ID, terminal_v7.job_id)) == 1

    queued_v7 = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=f"{prepared['business_key']}:v7-queued",
        prompt_version="monitoring-protocol-clause-structuring-v7",
    )
    assert queued_v7.status == MonitoringAiJobStatus.QUEUED
    assert (
        service._prompt_version_is_status_compatible(
            queued_v7,
            current_version,
        )
        is False
    )

    queued_v8 = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=f"{prepared['business_key']}:v8-queued",
        prompt_version="monitoring-protocol-clause-structuring-v8",
    )
    assert queued_v8.status == MonitoringAiJobStatus.QUEUED
    assert (
        service._prompt_version_is_status_compatible(
            queued_v8,
            current_version,
        )
        is False
    )

    # A queued v9 job is never claimable, retryable or reusable under the
    # v10 contract: it stays queued and is status-incompatible.
    queued_v9 = ai_service.submit_task(
        project_id=version.project_id,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=prepared["packet"].input_revision,
        input_payload=service._input_payload(version, topic, prepared),
        business_key=f"{prepared['business_key']}:v9-queued",
        prompt_version="monitoring-protocol-clause-structuring-v9",
    )
    assert queued_v9.status == MonitoringAiJobStatus.QUEUED
    assert (
        service._prompt_version_is_status_compatible(
            queued_v9,
            current_version,
        )
        is False
    )
    assert repository.get(PROJECT_ID, queued_v9.job_id).attempt_count == 0


def test_v1_job_is_audit_only_and_restart_creates_fresh_v2_contract(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, wakes = _service(
        tmp_path
    )
    legacy_job = _completed_legacy_protocol_job(
        service,
        ai_service,
        version=version,
        topic_id="study_treatment",
    )
    legacy_candidate = repository.candidates(
        PROJECT_ID,
        legacy_job.job_id,
    )[0]
    legacy_payload = repository.input_payload(PROJECT_ID, legacy_job.job_id)

    before_restart = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )
    assert before_restart["topics"][0]["status"] == "ready"
    assert before_restart["topics"][0]["job"] is None
    app = FastAPI()
    app.include_router(
        create_monitoring_protocol_preparation_router(
            service=service,
            require_server_principal=False,
        )
    )
    decision = TestClient(app).post(
        (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "protocol-preparation/protocol-versions/"
            f"{version.protocol_version_id}/candidates/"
            f"{legacy_candidate.candidate_id}/decision"
        ),
        json={
            "decision": "rejected",
            "actor": "medical_manager",
            "reason": "旧合同候选不得继续决定。",
            "expected_input_revision_sha256": (
                legacy_job.input_revision_sha256
            ),
            "expected_source_revision": legacy_payload["context"][
                "source_revision"
            ],
        },
    )
    assert decision.status_code == 409
    assert decision.json()["detail"]["code"] == (
        "monitoring_protocol_candidate_lineage_mismatch"
    )

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )

    all_jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    assert len(all_jobs) == 2
    current_job = next(job for job in all_jobs if job.job_id != legacy_job.job_id)
    current_payload = repository.input_payload(PROJECT_ID, current_job.job_id)
    assert restarted["topics"][0]["job"]["job_id"] == current_job.job_id
    assert current_job.status == MonitoringAiJobStatus.QUEUED
    assert current_payload["context"]["workflow"] == (
        PROTOCOL_PREPARATION_CONTRACT_VERSION
    )
    assert repository.candidates(PROJECT_ID, current_job.job_id) == ()

    retired = repository.get(PROJECT_ID, legacy_job.job_id)
    retained_candidate = repository.candidates(PROJECT_ID, legacy_job.job_id)[0]
    assert retired.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired.failure_code == "superseded_workflow_contract"
    assert retained_candidate.status == MonitoringAiCandidateStatus.SUPERSEDED
    assert retained_candidate.candidate_id == legacy_candidate.candidate_id
    assert retained_candidate.evidence == legacy_candidate.evidence
    assert repository.input_payload(PROJECT_ID, legacy_job.job_id) == legacy_payload
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            legacy_job.job_id,
            current_input_revision_sha256=legacy_job.input_revision_sha256,
        )
    assert wakes == ["wake"]


def test_startup_repository_recovery_retires_v1_before_worker_claim(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    current = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("safety_assessment",),
    )
    current_job_id = current["topics"][0]["job"]["job_id"]
    legacy_job = _queued_legacy_protocol_job(
        service,
        ai_service,
        version=version,
        topic_id="safety_assessment",
    )

    assert repository.expire_exhausted_leases() == 0

    retired = repository.get(PROJECT_ID, legacy_job.job_id)
    assert retired.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired.failure_code == "superseded_workflow_contract"
    claimed = repository.claim_next("startup-worker")
    assert claimed is not None
    assert claimed.job_id == current_job_id
    assert repository.input_payload(PROJECT_ID, legacy_job.job_id)["context"][
        "workflow"
    ] == "monitoring_protocol_preparation_v1"


def test_evidence_packet_v2_binds_table_row_and_preserves_stop_conflict(
    tmp_path: Path,
) -> None:
    resolver = ScientificShapeProtocolSpanResolver(
        match_ids_by_topic={
            "study_treatment": (
                "table-action",
                "ip-required",
                "ip-optional",
            )
        }
    )
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path,
        resolver=resolver,
    )

    started = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )
    job_id = started["topics"][0]["job"]["job_id"]
    payload = repository.input_payload(PROJECT_ID, job_id)
    evidence_by_source = {
        item["raw_fields"]["source_id"]: item
        for item in payload["evidence_packet"]
    }
    context = payload["context"]

    assert context["evidence_packet_version"] == (
        PROTOCOL_EVIDENCE_PACKET_VERSION
    )
    assert context["absence_assertion_authority"] == "none"
    assert set(evidence_by_source).issuperset(
        {
            "table-header-condition",
            "table-header-action",
            "table-threshold",
            "table-action",
            "ip-required",
            "ip-optional",
        }
    )
    threshold_context = evidence_by_source["table-threshold"]["raw_fields"][
        "protocol_context"
    ]
    assert "table_row_context" in threshold_context["roles"]
    assert threshold_context["structure"]["row_index"] == 2
    conflicts = context["detected_source_conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["object_scope"] == "investigational_product"
    assert conflicts[0]["action"] == "stop"
    assert set(conflicts[0]["modalities"]) == {"required", "optional"}
    assert set(conflicts[0]["evidence_ids"]) == {
        "evidence-ip-required",
        "evidence-ip-optional",
    }


def test_evidence_packet_v2_does_not_conflate_different_stop_conditions() -> None:
    conflicts = _detect_source_conflicts(
        (
            {
                "evidence_id": "evidence-infection",
                "quote": "发生严重感染时，受试者需停用研究药物。",
            },
            {
                "evidence_id": "evidence-clearance",
                "quote": "皮损完全清除3天后，受试者可停用研究药物。",
            },
        )
    )

    assert conflicts == []


def test_visit_topic_never_injects_medication_action_conflicts() -> None:
    """N10: medication-action conflicts are eligible only for study-
    treatment and concomitant-medication topics; a visit job must never be
    forced to emit an IP stop conflict merely because a visit word occurs in
    its source paragraph.
    """

    packet = (
        {
            "evidence_id": "evidence-visit-stop-required",
            "quote": "访视当天，受试者需停用研究药物。",
        },
        {
            "evidence_id": "evidence-visit-stop-optional",
            "quote": "访视当天，受试者可停用研究药物。",
        },
    )

    assert _detect_source_conflicts(
        packet,
        topic_id="visit_window_and_order",
    ) == []
    assert _detect_source_conflicts(
        packet,
        topic_id="eligibility_continuity",
    ) == []

    study_treatment_conflicts = _detect_source_conflicts(
        packet,
        topic_id="study_treatment",
    )
    assert len(study_treatment_conflicts) == 1
    assert study_treatment_conflicts[0]["object_scope"] == (
        "investigational_product"
    )
    assert set(study_treatment_conflicts[0]["evidence_ids"]) == {
        "evidence-visit-stop-required",
        "evidence-visit-stop-optional",
    }
    assert _detect_source_conflicts(
        packet,
        topic_id="concomitant_medication_policy",
    ) == []


def test_topic_object_conflict_pairing_is_exact() -> None:
    """Study-treatment jobs receive only investigational-product conflicts;
    concomitant-medication jobs receive only
    ``concomitant_non_investigational`` conflicts, each with the exact
    evidence set. A CM conflict must be absent from a study-treatment job
    and an IP conflict absent from a concomitant-medication job.
    """

    ip_packet = (
        {
            "evidence_id": "evidence-ip-stop-required",
            "quote": "受试者需停用研究药物。",
        },
        {
            "evidence_id": "evidence-ip-stop-optional",
            "quote": "受试者可停用研究药物。",
        },
    )
    cm_packet = (
        {
            "evidence_id": "evidence-cm-stop-required",
            "quote": "受试者需停用合并用药。",
        },
        {
            "evidence_id": "evidence-cm-stop-optional",
            "quote": "受试者可停用合并用药。",
        },
    )

    assert _detect_source_conflicts(
        cm_packet,
        topic_id="study_treatment",
    ) == []
    assert _detect_source_conflicts(
        ip_packet,
        topic_id="concomitant_medication_policy",
    ) == []

    ip_conflicts = _detect_source_conflicts(
        ip_packet,
        topic_id="study_treatment",
    )
    assert len(ip_conflicts) == 1
    assert ip_conflicts[0]["object_scope"] == "investigational_product"
    assert set(ip_conflicts[0]["evidence_ids"]) == {
        "evidence-ip-stop-required",
        "evidence-ip-stop-optional",
    }

    cm_conflicts = _detect_source_conflicts(
        cm_packet,
        topic_id="concomitant_medication_policy",
    )
    assert len(cm_conflicts) == 1
    assert cm_conflicts[0]["object_scope"] == (
        "concomitant_non_investigational"
    )
    assert set(cm_conflicts[0]["evidence_ids"]) == {
        "evidence-cm-stop-required",
        "evidence-cm-stop-optional",
    }


def test_estimand_target_population_alone_is_not_eligibility_evidence(
    tmp_path: Path,
) -> None:
    resolver = ScientificShapeProtocolSpanResolver(
        match_ids_by_topic={
            "eligibility_continuity": ("estimand-population",)
        }
    )
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path,
        resolver=resolver,
    )

    result = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("eligibility_continuity",),
    )

    assert result["status"] == "data_gap"
    assert result["topics"][0]["reason_code"] == "data_gap"
    assert repository.list_jobs(PROJECT_ID) == ()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("primary_match", "false"),
        ("primary_match", 1),
        ("eligible_for_rule_fact", "false"),
        ("eligible_for_rule_fact", 0),
    ),
)
def test_malformed_evidence_context_booleans_block_protocol_preparation(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    resolver = MalformedEvidenceContextResolver(field=field, value=value)
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path,
        resolver=resolver,
    )

    with pytest.raises(MonitoringProtocolPreparationError) as exc_info:
        service.start(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            topic_ids=("data_quality",),
        )

    assert exc_info.value.code == "monitoring_protocol_evidence_context_invalid"
    assert repository.list_jobs(PROJECT_ID) == ()


def test_explicit_start_retries_same_revision_failed_topic(
    tmp_path: Path,
) -> None:
    service, repository, _ai_service, _provider, version, wakes = _service(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("safety_assessment",),
    )
    claimed = repository.claim_next("failed-topic-worker")
    assert claimed is not None
    failed = repository.fail(
        claimed,
        owner="failed-topic-worker",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )
    assert failed.status == MonitoringAiJobStatus.FAILED

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("safety_assessment",),
    )

    assert restarted["topics"][0]["status"] == "queued"
    assert (
        repository.get(PROJECT_ID, failed.job_id).status
        == MonitoringAiJobStatus.QUEUED
    )
    assert wakes == ["wake", "wake"]


def test_status_ignores_job_with_obsolete_revision_hash(
    tmp_path: Path,
) -> None:
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    started = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("safety_assessment",),
    )
    job_id = started["topics"][0]["job"]["job_id"]
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_jobs
            SET status = ?, input_revision_sha256 = ?
            WHERE project_id = ? AND job_id = ?
            """,
            (
                MonitoringAiJobStatus.STALE_INPUT.value,
                "f" * 64,
                PROJECT_ID,
                job_id,
            ),
        )

    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("safety_assessment",),
    )

    assert status["topics"][0]["status"] == "ready"
    assert status["topics"][0]["job"] is None


def test_source_gap_is_explicit_and_does_not_submit_ai_job(
    tmp_path: Path,
) -> None:
    resolver = FakeProtocolSpanResolver(gap_topics=("data_quality",))
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path,
        resolver=resolver,
    )

    result = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("data_quality",),
    )

    assert result["status"] == "data_gap"
    assert result["progress"]["data_gap"] == 1
    assert result["topics"][0]["status"] == "data_gap"
    assert result["topics"][0]["execution_status"] == "skipped"
    assert result["topics"][0]["reason_code"] == "data_gap"
    assert "未提交 AI 作业" in result["topics"][0]["data_gap"]
    assert result["topics"][0]["candidates"] == []
    assert repository.list_jobs(PROJECT_ID) == ()
    assert resolver.resolve_calls == []


def test_completed_candidates_remain_pending_user_confirmation_and_traceable(
    tmp_path: Path,
) -> None:
    service, _repository, ai_service, provider, version, _wakes = _service(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )

    run = ai_service.run_next("protocol-preparation-worker")
    result = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )

    assert run.processed is True
    assert provider.run_count == 1
    assert result["status"] == "candidate_review"
    topic = result["topics"][0]
    assert topic["status"] == "candidate_review"
    assert set(topic["job"]) == {
        "job_id",
        "status",
        "attempt_count",
        "failure_code",
        "failure_message",
        "updated_at",
    }
    candidate = topic["candidates"][0]
    assert candidate["status"] == "proposed"
    assert candidate["review_status"] == "pending_user_confirmation"
    assert candidate["evidence"][0]["locator"].startswith("docx:span:")
    assert candidate["evidence"][0]["quote"].endswith("真实方案原文。")
    serialized = str(result)
    assert "待医学批准" not in serialized
    assert "已医学批准" not in serialized


def test_public_candidate_excludes_unreferenced_authorized_evidence(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )
    ai_service.run_next("protocol-preparation-worker")
    job = repository.list_jobs(
        PROJECT_ID,
        task_type="protocol_clause_structuring",
    )[0]
    candidate = repository.candidates(PROJECT_ID, job.job_id)[0]
    referenced = candidate.evidence[0]
    unrelated = referenced.model_copy(
        update={
            "evidence_id": "evidence-unrelated-authorized-span",
            "locator": "docx:span:unrelated",
            "quote": "同一作业已授权但当前候选未引用的方案原文。",
        }
    )
    restricted = candidate.model_copy(
        update={
            "structured_payload": {
                **candidate.structured_payload,
                "evidence_ids": [referenced.evidence_id],
            },
            "claims": tuple(
                claim.model_copy(
                    update={"evidence_ids": (referenced.evidence_id,)}
                )
                for claim in candidate.claims
            ),
            "evidence": (*candidate.evidence, unrelated),
        }
    )

    public = service._public_candidate(restricted)

    assert [item["evidence_id"] for item in public["evidence"]] == [
        referenced.evidence_id
    ]
    assert public["confidence_summary"]["requires_user_review"] is True
    assert public["confidence_summary"]["automation_permitted"] is False


def test_low_confidence_acceptance_requires_a_medical_explanation(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )
    db_path = tmp_path / "monitoring-ai.sqlite3"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT candidate_json FROM monitoring_ai_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["claims"][0]["confidence"] = 0.40
        connection.execute(
            "UPDATE monitoring_ai_candidates SET candidate_json = ? WHERE candidate_id = ?",
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                candidate_id,
            ),
        )
        connection.commit()

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="低于工作台置信度阈值",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="",
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
        )


def test_rejects_unconfirmed_cross_project_and_source_revision_mismatch(
    tmp_path: Path,
) -> None:
    protocol_repository = MonitoringProtocolRuleRepository(
        tmp_path / "protocol-rules.sqlite3"
    )
    draft = protocol_repository.register_protocol_version(
        _version(status="draft")
    )
    ai_repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    ai_service = MonitoringAiService(ai_repository)
    resolver = FakeProtocolSpanResolver(source_hash="b" * 64)
    service = MonitoringProtocolPreparationService(
        protocol_repository=protocol_repository,
        ai_repository=ai_repository,
        ai_service=ai_service,
        source_registry=FakeSourceRegistry(),
        source_packet_resolver=resolver.resolve,
        source_span_searcher=resolver.search,
    )

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="只有已确认",
    ):
        service.start(
            project_id=PROJECT_ID,
            protocol_version_id=draft.protocol_version_id,
        )
    with pytest.raises(MonitoringProtocolPreparationError) as cross_project:
        service.status(
            project_id=OTHER_PROJECT_ID,
            protocol_version_id=draft.protocol_version_id,
        )
    assert cross_project.value.http_status == 404

    confirmed_repository = MonitoringProtocolRuleRepository(
        tmp_path / "confirmed-protocol-rules.sqlite3"
    )
    confirmed = confirmed_repository.register_protocol_version(_version())
    mismatch_service = MonitoringProtocolPreparationService(
        protocol_repository=confirmed_repository,
        ai_repository=ai_repository,
        ai_service=ai_service,
        source_registry=FakeSourceRegistry(),
        source_packet_resolver=resolver.resolve,
        source_span_searcher=resolver.search,
    )
    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="来源或内容版本不一致",
    ):
        mismatch_service.start(
            project_id=PROJECT_ID,
            protocol_version_id=confirmed.protocol_version_id,
            topic_ids=("study_treatment",),
        )


def test_rejects_registered_protocol_without_usable_parsed_spans(
    tmp_path: Path,
) -> None:
    protocol_repository = MonitoringProtocolRuleRepository(
        tmp_path / "protocol-rules.sqlite3"
    )
    version = protocol_repository.register_protocol_version(_version())
    ai_repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    resolver = FakeProtocolSpanResolver()
    service = MonitoringProtocolPreparationService(
        protocol_repository=protocol_repository,
        ai_repository=ai_repository,
        ai_service=MonitoringAiService(ai_repository),
        source_registry=FakeSourceRegistry(
            parser_status="parse_failed",
            span_count=0,
        ),
        source_packet_resolver=resolver.resolve,
        source_span_searcher=resolver.search,
    )

    with pytest.raises(MonitoringProtocolPreparationError) as error:
        service.start(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
        )

    assert error.value.code == "monitoring_protocol_source_not_parsed"
    assert ai_repository.list_jobs(PROJECT_ID) == ()
    assert resolver.search_calls == []


def test_router_exposes_compact_start_and_status_contract(tmp_path: Path) -> None:
    service, _repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_protocol_preparation_router(
            service=service,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    base = (
        f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
        f"protocol-preparation/protocol-versions/{version.protocol_version_id}"
    )

    started = client.post(f"{base}/start")
    status = client.get(f"{base}/status")
    invalid = client.post(
        f"{base}/start",
        json={"topic_ids": ["unknown-topic"]},
    )

    assert started.status_code == 202, started.text
    assert started.json()["progress"]["queued"] == len(
        DEFAULT_MONITORING_PROTOCOL_TOPICS
    )
    assert status.status_code == 200, status.text
    assert status.json()["progress"]["total"] == len(
        DEFAULT_MONITORING_PROTOCOL_TOPICS
    )
    assert invalid.status_code == 422
    assert (
        invalid.json()["detail"]["code"]
        == "monitoring_protocol_topic_invalid"
    )


def _completed_topic_candidate(
    service: MonitoringProtocolPreparationService,
    repository: MonitoringAiRepository,
    ai_service: MonitoringAiService,
    version: ProtocolSourceVersion,
    *,
    topic_id: str,
) -> tuple[str, str, str]:
    service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic_id,),
    )
    run = ai_service.run_next("protocol-preparation-decision-worker")
    assert run.processed is True
    status = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic_id,),
    )
    topic = status["topics"][0]
    candidate_id = topic["candidates"][0]["candidate_id"]
    job = repository.job_for_candidate(PROJECT_ID, candidate_id)
    return (
        candidate_id,
        job.input_revision_sha256,
        topic["source_revision"],
    )


def test_acceptance_is_idempotent_and_creates_traceable_fact_draft(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )

    first = service.decide_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical_manager",
        reason="结构化条款与方案原文一致。",
        expected_input_revision_sha256=input_revision,
        expected_source_revision=source_revision,
    )
    second = service.decide_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical_manager",
        reason="同一决定重试。",
        expected_input_revision_sha256=input_revision,
        expected_source_revision=source_revision,
    )

    assert first["candidate"]["status"] == "accepted"
    assert first["candidate"]["review_status"] == "user_confirmed"
    assert first["decision_reused"] is False
    assert second["decision_reused"] is True
    assert first["outcome"]["state"] == "user_confirmed_fact_draft"
    assert second["outcome"]["fact_reused"] is True
    assert (
        first["outcome"]["fact"]["fact_revision_id"]
        == second["outcome"]["fact"]["fact_revision_id"]
    )
    assert (
        first["outcome"]["next_action"]["code"]
        == "review_rule_template_and_compile"
    )
    serialized = str(first)
    assert "待医学批准" not in serialized
    assert "不会再次批准同一候选" in serialized

    facts = service.protocol_repository.facts_for_version(
        version.protocol_version_id
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.status == "ai_candidate"
    assert fact.fact_type == "data_quality"
    assert fact.source_entry_id == SOURCE_ENTRY_ID
    assert fact.source_locator.startswith("docx:span:")
    assert fact.source_text.endswith("真实方案原文。")
    adoption = fact.normalized_payload["adoption_context"]
    assert adoption["source_revision"] == source_revision
    assert adoption["source_content_sha256"] == SOURCE_HASH
    assert adoption["protocol_version_id"] == version.protocol_version_id
    assert adoption["adoption_basis"] == "medical_manager_explicit_selection"
    assert len(adoption["candidate_snapshot_sha256"]) == 64
    assert first["source_snapshot"]["evidence"][0]["quote"].endswith(
        "真实方案原文。"
    )
    refreshed = service.status(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("data_quality",),
    )
    projected_fact = refreshed["topics"][0]["candidates"][0]["fact"]
    assert projected_fact == {
        "fact_revision_id": fact.fact_revision_id,
        "state_version": fact.state_version,
        "status": "ai_candidate",
        "fact_type": "data_quality",
        "title": fact.title,
    }


def test_rejection_is_idempotent_and_never_creates_protocol_fact(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )

    first = service.decide_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.REJECTED,
        actor="medical_manager",
        reason="候选拆分粒度不符合原文。",
        expected_input_revision_sha256=input_revision,
        expected_source_revision=source_revision,
    )
    second = service.decide_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.REJECTED,
        actor="medical_manager",
        reason="同一决定重试。",
        expected_input_revision_sha256=input_revision,
        expected_source_revision=source_revision,
    )

    assert first["outcome"]["state"] == "user_rejected"
    assert first["outcome"]["fact"] is None
    assert second["decision_reused"] is True
    assert (
        service.protocol_repository.facts_for_version(
            version.protocol_version_id
        )
        == ()
    )
    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="不能覆盖原决定",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="尝试覆盖。",
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
        )


def test_accepted_candidate_without_fact_is_recovered_on_same_decision_retry(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )
    repository.decide_candidate(
        PROJECT_ID,
        candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical_manager",
        reason="模拟候选决定已写入、事实投影尚未完成。",
        current_input_revision_sha256=input_revision,
    )

    recovered = service.decide_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical_manager",
        reason="恢复同一请求。",
        expected_input_revision_sha256=input_revision,
        expected_source_revision=source_revision,
    )

    assert recovered["decision_reused"] is True
    assert recovered["outcome"]["fact_reused"] is False
    assert recovered["outcome"]["state"] == "user_confirmed_fact_draft"
    facts = service.protocol_repository.facts_for_version(
        version.protocol_version_id
    )
    assert len(facts) == 1


def test_acceptance_requires_current_frozen_identity_and_topic_fact_type(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="study_treatment",
    )

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="请选择与候选含义一致的类型",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="",
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
        )
    current = repository.candidates(
        PROJECT_ID,
        repository.job_for_candidate(PROJECT_ID, candidate_id).job_id,
    )[0]
    assert current.status == MonitoringAiCandidateStatus.PROPOSED


    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="输入或方案来源修订已变化",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="",
            expected_input_revision_sha256=input_revision,
            expected_source_revision="mpr_stale",
            proposed_fact_type="study_treatment_change",
        )
    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="不属于该监查主题",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="",
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
            proposed_fact_type="concomitant_medication_prohibited",
        )
    current = repository.candidates(
        PROJECT_ID,
        repository.job_for_candidate(PROJECT_ID, candidate_id).job_id,
    )[0]
    assert current.status == MonitoringAiCandidateStatus.PROPOSED


def test_candidate_lineage_rejects_noncanonical_input_revision_digest(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="study_treatment",
    )

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="输入或方案来源修订已变化",
    ):
        service._frozen_candidate_context(
            version=version,
            candidate_id=candidate_id,
            expected_input_revision_sha256=f" {input_revision}",
            expected_source_revision=source_revision,
        )


@pytest.mark.parametrize(
    "source_content_sha256",
    [f" {SOURCE_HASH}", SOURCE_HASH.upper(), 123],
)
def test_candidate_evidence_rejects_noncanonical_source_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_content_sha256: object,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="study_treatment",
    )
    job_id = repository.job_for_candidate(PROJECT_ID, candidate_id).job_id
    payload = repository.input_payload(PROJECT_ID, job_id)
    payload["evidence_packet"][0]["source_content_sha256"] = source_content_sha256
    monkeypatch.setattr(
        repository,
        "input_payload",
        lambda _project_id, _job_id: payload,
    )

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="候选证据与冻结方案原文",
    ):
        service._frozen_candidate_context(
            version=version,
            candidate_id=candidate_id,
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
        )


def test_decision_fails_closed_when_registered_protocol_source_drifted(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )
    service.source_registry.source_hash = "b" * 64

    with pytest.raises(
        MonitoringProtocolPreparationError,
        match="来源登记不一致",
    ):
        service.decide_candidate(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            actor="medical_manager",
            reason="",
            expected_input_revision_sha256=input_revision,
            expected_source_revision=source_revision,
        )

    current = repository.candidates(
        PROJECT_ID,
        repository.job_for_candidate(PROJECT_ID, candidate_id).job_id,
    )[0]
    assert current.status == MonitoringAiCandidateStatus.PROPOSED
    assert (
        service.protocol_repository.facts_for_version(
            version.protocol_version_id
        )
        == ()
    )


def test_router_candidate_decision_returns_fact_draft_and_conflict(
    tmp_path: Path,
) -> None:
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    candidate_id, input_revision, source_revision = _completed_topic_candidate(
        service,
        repository,
        ai_service,
        version,
        topic_id="data_quality",
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_protocol_preparation_router(
            service=service,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    decision_url = (
        f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
        f"protocol-preparation/protocol-versions/{version.protocol_version_id}/"
        f"candidates/{candidate_id}/decision"
    )
    accepted = client.post(
        decision_url,
        json={
            "decision": "accepted",
            "actor": "medical_manager",
            "reason": "原文一致。",
            "expected_input_revision_sha256": input_revision,
            "expected_source_revision": source_revision,
        },
    )
    opposite = client.post(
        decision_url,
        json={
            "decision": "rejected",
            "actor": "medical_manager",
            "reason": "覆盖原决定。",
            "expected_input_revision_sha256": input_revision,
            "expected_source_revision": source_revision,
        },
    )

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["outcome"]["state"] == "user_confirmed_fact_draft"
    assert opposite.status_code == 409
    assert (
        opposite.json()["detail"]["code"]
        == "monitoring_protocol_candidate_decision_conflict"
    )


def test_provider_receives_focused_bundle_view_while_payload_stays_frozen(
    tmp_path: Path,
) -> None:
    import json

    class FocusedViewProtocolProvider(FakeProductAiProvider):
        def __init__(self):
            super().__init__()
            self.envelopes = []

        def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
            self.envelopes.append(envelope)
            self.run_count += 1
            input_payload = envelope.payload["input_payload"]
            evidence_ids = [
                item["evidence_id"]
                for item in input_payload["evidence_packet"]
            ]
            conflict = input_payload["context"]["detected_source_conflicts"][0]
            return {
                "schema_version": "monitoring_ai_v1",
                "task_id": envelope.task_id,
                "task_type": "protocol_clause_structuring",
                "input_revision_sha256": envelope.payload[
                    "input_revision_sha256"
                ],
                "candidates": [
                    {
                        "candidate_type": "protocol_clause_structure",
                        "title": "暂停与停药条款结构化候选",
                        "text": "仅供用户基于原文确认。",
                        "structured_payload": {
                            "clause_id": "clause-study-treatment",
                            "fact_type": input_payload["context"][
                                "candidate_fact_types"
                            ][0],
                            "subject_scope": "方案规定的适用受试者",
                            "conditions": ["ALT或AST>3×ULN"],
                            "time_windows": ["48小时内"],
                            "thresholds": ["ALT或AST>3×ULN"],
                            "exceptions": [],
                            "required_actions": ["复查并暂停研究药物"],
                            "evidence_ids": evidence_ids,
                            "source_conflicts": [
                                {
                                    "conflict_id": conflict["conflict_id"],
                                    "action": conflict["action"],
                                    "modalities": list(conflict["modalities"]),
                                    "status": "requires_user_resolution",
                                    "evidence_ids": list(
                                        conflict["evidence_ids"]
                                    ),
                                }
                            ],
                        },
                        "claims": [
                            {
                                "claim_id": "claim-conflict-stop",
                                "kind": "data_gap",
                                "text": "原文对同一停药动作存在强制与可选措辞冲突。",
                                "confidence": 0.9,
                                "uncertainty": "冲突原文均有效，系统不得代替用户裁决。",
                                "user_action": "请基于并列原文确认最终执行要求。",
                                "evidence_ids": list(conflict["evidence_ids"]),
                            }
                        ],
                    }
                ],
            }

    resolver = ScientificShapeProtocolSpanResolver(
        match_ids_by_topic={
            "study_treatment": (
                "table-action",
                "ip-required",
                "ip-optional",
            )
        }
    )
    protocol_repository = MonitoringProtocolRuleRepository(
        tmp_path / "protocol-rules.sqlite3"
    )
    version = protocol_repository.register_protocol_version(_version())
    ai_repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    provider = FocusedViewProtocolProvider()
    ai_service = MonitoringAiService(
        ai_repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider=provider.provider_name,
            model=provider.model_name,
            env={
                "WORKBENCH_AI_PROVIDER": provider.provider_name,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": provider.model_name,
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": provider.model_name,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: provider,
    )
    service = MonitoringProtocolPreparationService(
        protocol_repository=protocol_repository,
        ai_repository=ai_repository,
        ai_service=ai_service,
        source_registry=FakeSourceRegistry(),
        source_packet_resolver=resolver.resolve,
        source_span_searcher=resolver.search,
        source_context_expander=resolver.expand,
    )

    service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=("study_treatment",),
    )
    run = ai_service.run_next("protocol-preparation-worker")
    assert run.processed is True
    assert run.job is not None
    assert run.job.status == MonitoringAiJobStatus.COMPLETED

    job_id = run.job.job_id
    persisted = ai_repository.input_payload(PROJECT_ID, job_id)
    persisted_ids = [
        item["evidence_id"] for item in persisted["evidence_packet"]
    ]
    envelope_payload = provider.envelopes[0].payload["input_payload"]
    focused_ids = [
        item["evidence_id"]
        for item in envelope_payload["evidence_packet"]
    ]
    assert set(focused_ids) == {
        "evidence-ip-heading",
        "evidence-table-header-condition",
        "evidence-table-header-action",
        "evidence-table-threshold",
        "evidence-table-action",
        "evidence-ip-required",
        "evidence-ip-optional",
    }
    assert len(focused_ids) < len(persisted_ids)
    assert set(focused_ids).issubset(persisted_ids)
    assert len(
        json.dumps(envelope_payload["evidence_packet"], ensure_ascii=False)
    ) < len(json.dumps(persisted["evidence_packet"], ensure_ascii=False))
    focus = envelope_payload["context"]["provider_evidence_focus"]
    assert focus["full_document_coverage_asserted"] is False
    assert focus["retained_evidence_count"] == len(focused_ids)
    assert focus["source_evidence_count"] == len(persisted_ids)
    assert focus["max_evidence_ids_per_candidate"] == 50
    assert "provider_evidence_focus" not in persisted["context"]
    assert "不得超过 50 个" in envelope_payload["context"]["instruction"]
    assert provider.run_count == 1
    candidates = ai_repository.candidates(PROJECT_ID, job_id)
    assert len(candidates) == 1
    assert candidates[0].status == MonitoringAiCandidateStatus.PROPOSED


class FailingV7VisitProvider:
    """Product provider that always emits a first-dose visit candidate,
    which is deterministically invalid under the v7 visit gates."""

    provider_name = "test-product-ai"
    model_name = "test-product-model"
    expected_response_model = "test-product-model"
    response_model = "test-product-model"
    transport_name = "openai_compatible"

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        input_payload = envelope.payload.get("input_payload")
        if input_payload is None:
            input_payload = envelope.payload["original_task"]["input_payload"]
        evidence_ids = [
            item["evidence_id"]
            for item in input_payload["evidence_packet"]
        ]
        candidate_fact_types = input_payload["context"].get(
            "candidate_fact_types"
        ) or ["safety_assessment"]
        revision_hash = envelope.payload.get("input_revision_sha256")
        if revision_hash is None:
            revision_hash = envelope.payload["original_task"][
                "input_revision_sha256"
            ]
        return {
            "schema_version": "monitoring_ai_v1",
            "task_id": envelope.task_id,
            "task_type": "protocol_clause_structuring",
            "input_revision_sha256": revision_hash,
            "candidates": [
                {
                    "candidate_type": "protocol_clause_structure",
                    "title": "v7失败候选",
                    "text": "计划访视应在允许时间窗内完成。",
                    "structured_payload": {
                        "clause_id": "clause-v7-fail",
                        "fact_type": str(candidate_fact_types[0]).strip(),
                        "subject_scope": "方案规定的适用受试者",
                        "conditions": [],
                        "time_windows": ["访视窗内"],
                        "thresholds": [],
                        "exceptions": [],
                        "required_actions": ["访视当天完成第一次用药"],
                        "evidence_ids": evidence_ids,
                    },
                    "claims": [
                        {
                            "claim_id": "claim-v7-fail",
                            "kind": "fact",
                            "text": "方案原文包含该监查主题相关条款。",
                            "confidence": 0.9,
                            "uncertainty": "",
                            "user_action": "核对结构化字段与方案原文。",
                            "evidence_ids": evidence_ids,
                        }
                    ],
                }
            ],
        }


def test_v12_cutover_start_creates_distinct_job_and_never_reuses_v7(
    tmp_path: Path,
) -> None:
    """Decisive cutover: same-business-key queued and failed v7 jobs exist,
    protocol preparation start() creates a distinct v12 job, the v7 attempt
    counts never increase, and no v7 job is claimed/retried/reused while
    terminal history stays queryable."""
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    business_key = prepared["business_key"]
    v7_prompt = "monitoring-protocol-clause-structuring-v7"

    def v7_request(suffix: str) -> MonitoringAiJobCreate:
        return MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=MonitoringAiInputRevision(
                project_id=PROJECT_ID,
                batch_revision=f"legacy-v7-{suffix}",
                protocol_version="protocol-registry-v1",
                sources=(
                    MonitoringAiSourceBinding(
                        source_entry_id=SOURCE_ENTRY_ID,
                        source_content_sha256=SOURCE_HASH,
                    ),
                ),
            ),
            input_payload=payload,
            prompt_version=v7_prompt,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=business_key,
        )

    failed_v7 = repository.create_or_get(v7_request("failed"))
    queued_v7 = repository.create_or_get(v7_request("queued"))
    assert failed_v7.job_id != queued_v7.job_id
    assert failed_v7.prompt_version == v7_prompt
    assert queued_v7.prompt_version == v7_prompt
    assert failed_v7.status == MonitoringAiJobStatus.QUEUED
    assert queued_v7.status == MonitoringAiJobStatus.QUEUED

    failing_provider = FailingV7VisitProvider()
    failing_service = MonitoringAiService(
        repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider=failing_provider.provider_name,
            model=failing_provider.model_name,
            env={
                "WORKBENCH_AI_PROVIDER": failing_provider.provider_name,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": failing_provider.model_name,
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": (
                    failing_provider.model_name
                ),
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: failing_provider,
    )
    failed_result = failing_service.run_next("v7-failure-worker")
    assert failed_result.processed is True
    assert failed_result.job is not None
    assert failed_result.job.job_id == failed_v7.job_id
    assert failed_result.job.status == MonitoringAiJobStatus.FAILED
    assert failed_result.job.failure_code == "invalid_ai_output"
    assert failed_result.job.attempt_count == 1
    assert repository.get(PROJECT_ID, queued_v7.job_id).status == (
        MonitoringAiJobStatus.QUEUED
    )

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )

    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v12_job = next(
        job
        for job in jobs
        if job.prompt_version
        == "monitoring-protocol-clause-structuring-v12"
    )
    assert v12_job.job_id not in {failed_v7.job_id, queued_v7.job_id}
    assert v12_job.status == MonitoringAiJobStatus.QUEUED
    assert restarted["topics"][0]["job"]["job_id"] == v12_job.job_id

    superseded_failed = repository.get(PROJECT_ID, failed_v7.job_id)
    superseded_queued = repository.get(PROJECT_ID, queued_v7.job_id)
    # The failed v7 job is superseded with the explicit contract code; the
    # queued v7 job is retired through the stale-input revision gate first
    # (no failure code), then skipped by the contract supersede. Both are
    # STALE_INPUT and therefore never claimable, retryable or reusable.
    assert superseded_failed.status == MonitoringAiJobStatus.STALE_INPUT
    assert superseded_failed.failure_code == "superseded_job_contract"
    assert superseded_queued.status == MonitoringAiJobStatus.STALE_INPUT
    # v7 attempt counts are frozen by the cutover: the failed run stays at
    # one attempt and the queued job is never claimed.
    assert superseded_failed.attempt_count == 1
    assert superseded_queued.attempt_count == 0

    result = ai_service.run_next("v12-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v12_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == (
        "monitoring-protocol-clause-structuring-v12"
    )
    assert result.job.attempt_count == 1
    assert len(repository.candidates(PROJECT_ID, v12_job.job_id)) == 1

    # No v7 job was claimed, retried or reused after the cutover.
    assert repository.get(PROJECT_ID, failed_v7.job_id).attempt_count == 1
    assert repository.get(PROJECT_ID, queued_v7.job_id).attempt_count == 0
    assert repository.get(PROJECT_ID, failed_v7.job_id).status == (
        MonitoringAiJobStatus.STALE_INPUT
    )
    assert repository.get(PROJECT_ID, queued_v7.job_id).status == (
        MonitoringAiJobStatus.STALE_INPUT
    )
    # Terminal history remains queryable.
    assert repository.get(PROJECT_ID, failed_v7.job_id).job_id == (
        failed_v7.job_id
    )
    assert repository.get(PROJECT_ID, queued_v7.job_id).job_id == (
        queued_v7.job_id
    )


def test_v11_terminal_failure_is_frozen_and_distinct_v12_job_is_created(
    tmp_path: Path,
) -> None:
    """The exact previous prompt identity remains immutable at v12 cutover.

    A same-revision terminal v11 failure keeps its status, failure evidence,
    attempt lineage and zero candidates; startup marks it retired, refuses
    retry/reuse, and creates a distinct v12 job on the same business key.
    """
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    input_revision = prepared["packet"].input_revision
    input_payload = service._input_payload(version, topic, prepared)
    business_key = prepared["business_key"]
    v11_prompt = "monitoring-protocol-clause-structuring-v11"
    v12_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]
    assert v12_prompt == "monitoring-protocol-clause-structuring-v12"
    assert v11_prompt not in PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    assert v11_prompt in PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS

    frozen_v11 = ai_service.submit_task(
        project_id=PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=input_revision,
        input_payload=input_payload,
        business_key=business_key,
        prompt_version=v11_prompt,
    )
    claimed = repository.claim_next("frozen-v11-worker")
    assert claimed is not None
    assert claimed.job_id == frozen_v11.job_id
    failure_message = (
        "provider output remained invalid after one controlled repair: "
        "candidates[0].claims[2].uncertainty matched 回收"
    )
    request_payload = {
        "envelope": {"prompt_version": v11_prompt},
        "repair_envelope": {
            "prompt_version": f"{v11_prompt}:json-repair-1"
        },
    }
    response_payload = {
        "provider_outputs": [{"attempt": 1}, {"attempt": 2}],
        "validation_diagnostics": [
            {
                "code": "visit_topic_forbidden_family",
                "candidate_index": 0,
                "candidate_number": 1,
                "field_path": "candidates[0].claims[2].uncertainty",
                "matched_token": "回收",
                "forbidden_family": (
                    "dispensing_return_weighing_adherence_pk"
                ),
                "repair_action": "regenerate_entire_user_visible_field",
            }
        ],
    }
    repository.record_attempt(
        claimed,
        owner="frozen-v11-worker",
        request_payload=request_payload,
        response_payload=response_payload,
        response_model="test-product-model",
        outcome="invalid_output",
        failure_code="invalid_ai_output",
        failure_message=failure_message,
    )
    failed = repository.fail(
        claimed,
        owner="frozen-v11-worker",
        failure_code="invalid_ai_output",
        failure_message=failure_message,
        retryable=False,
    )
    frozen_updated_at = failed.updated_at
    frozen_attempt = repository.attempts(
        PROJECT_ID,
        frozen_v11.job_id,
    )[0]
    assert repository.candidates(PROJECT_ID, frozen_v11.job_id) == ()

    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version=v12_prompt,
        legacy_terminal_prompt_versions=(
            PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
        ),
    )
    assert changed == 0
    preserved = repository.get(PROJECT_ID, frozen_v11.job_id)
    assert preserved.status == MonitoringAiJobStatus.FAILED
    assert preserved.failure_code == "invalid_ai_output"
    assert preserved.retryable is False
    assert preserved.prompt_version == v11_prompt
    assert preserved.updated_at == frozen_updated_at
    assert preserved.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert preserved.contract_retired_at is not None
    assert repository.candidates(PROJECT_ID, frozen_v11.job_id) == ()
    preserved_attempt = repository.attempts(
        PROJECT_ID,
        frozen_v11.job_id,
    )[0]
    assert preserved_attempt["attempt_id"] == frozen_attempt["attempt_id"]
    assert preserved_attempt["request_sha256"] == (
        frozen_attempt["request_sha256"]
    )
    assert preserved_attempt["response_sha256"] == (
        frozen_attempt["response_sha256"]
    )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            frozen_v11.job_id,
            current_input_revision_sha256=input_revision.revision_sha256,
        )

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v12_job = next(
        job for job in jobs if job.prompt_version == v12_prompt
    )
    assert v12_job.job_id != frozen_v11.job_id
    assert v12_job.business_key == business_key
    assert v12_job.input_revision_sha256 == input_revision.revision_sha256
    assert restarted["topics"][0]["job"]["job_id"] == v12_job.job_id

    result = ai_service.run_next("v12-worker")
    assert result.job is not None
    assert result.job.job_id == v12_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v12_prompt
    assert len(repository.candidates(PROJECT_ID, v12_job.job_id)) == 1
    final_v11 = repository.get(PROJECT_ID, frozen_v11.job_id)
    assert final_v11.status == MonitoringAiJobStatus.FAILED
    assert final_v11.updated_at == frozen_updated_at
    assert final_v11.attempt_count == 1
    assert repository.candidates(PROJECT_ID, frozen_v11.job_id) == ()


def test_v9_to_v12_cutover_same_revision_retires_active_and_preserves_terminal(
    tmp_path: Path,
) -> None:
    """Decisive v9→v12 cutover on one identical protocol input revision.

    v9 (and the frozen v10 identity) are absent from the status-compatible
    legacy set but present in the retirement-audit set, so the startup
    supersession preserves terminal completed/failed v9 rows (status,
    failure evidence, retryable value, timestamps, attempt lineage,
    candidates) while durably marking them with the
    superseded-prompt-contract code; queued and running v9 rows are
    retired to STALE_INPUT. Preserved v9 history is never
    status-compatible, retryable or reusable under v12. A late completion
    from the retired running v9 loses CAS and persists zero candidates, no
    retired v9 job can be claimed or retried, and a distinct v12 job is
    created, selected and completed while every v9 id and attempt count
    stays untouched. Revision drift cannot explain the retirement because
    the v9 rows and the fresh v12 job share the same input revision.
    """
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    input_revision = prepared["packet"].input_revision
    v9_prompt = "monitoring-protocol-clause-structuring-v9"
    v12_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]
    assert v12_prompt == "monitoring-protocol-clause-structuring-v12"
    assert v9_prompt not in PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    assert v9_prompt in PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS

    def v9_request(suffix: str) -> MonitoringAiJobCreate:
        return MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=input_revision,
            input_payload=payload,
            prompt_version=v9_prompt,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=f"{prepared['business_key']}:{suffix}",
        )

    def late_v9_candidate(job: MonitoringAiJob) -> MonitoringAiCandidate:
        evidence = MonitoringAiEvidence(
            evidence_id="evidence-late-v9",
            source_entry_id=SOURCE_ENTRY_ID,
            source_content_sha256=SOURCE_HASH,
            locator="docx:span:late-v9",
            raw_fields={"source_id": "late-v9"},
            input_revision_sha256=job.input_revision_sha256,
        )
        claim = MonitoringAiClaim(
            claim_id="claim-late-v9",
            kind=MonitoringAiClaimKind.RECOMMENDATION,
            text="延迟返回的 v9 候选不得持久化。",
            confidence=0.9,
            uncertainty="该延迟返回不代表任何可采用的候选。",
            user_action="无需处理。",
            evidence_ids=(evidence.evidence_id,),
        )
        return MonitoringAiCandidate(
            candidate_id="candidate-late-v9",
            job_id=job.job_id,
            project_id=job.project_id,
            task_type=job.task_type,
            candidate_type="protocol_clause_structure",
            title="延迟 v9 条款结构化候选",
            structured_payload={"clause_id": "clause-late-v9"},
            claims=(claim,),
            evidence=(evidence,),
            input_revision_sha256=job.input_revision_sha256,
            prompt_version=job.prompt_version,
            created_at=datetime.now(timezone.utc),
        )

    completed_v9 = repository.create_or_get(v9_request("v9-completed"))
    completed = ai_service.run_next("v9-completed-worker")
    assert completed.processed is True
    assert completed.job is not None
    assert completed.job.job_id == completed_v9.job_id
    assert completed.job.status == MonitoringAiJobStatus.COMPLETED
    assert completed.job.attempt_count == 1
    v9_candidate = repository.candidates(PROJECT_ID, completed_v9.job_id)[0]
    terminal_completed = repository.get(PROJECT_ID, completed_v9.job_id)

    failed_v9 = repository.create_or_get(v9_request("v9-failed"))
    failed_claimed = repository.claim_next("v9-failed-worker")
    assert failed_claimed is not None
    assert failed_claimed.job_id == failed_v9.job_id
    repository.record_attempt(
        failed_claimed,
        owner="v9-failed-worker",
        request_payload={"prompt": v9_prompt},
        response_payload=None,
        outcome="provider_error",
        failure_code="provider_timeout",
        failure_message="provider timed out",
    )
    failed = repository.fail(
        failed_claimed,
        owner="v9-failed-worker",
        failure_code="provider_timeout",
        failure_message="provider timed out",
        retryable=False,
    )
    assert failed.status == MonitoringAiJobStatus.FAILED
    assert failed.attempt_count == 1
    terminal_failed = repository.get(PROJECT_ID, failed_v9.job_id)

    running_v9 = repository.create_or_get(v9_request("v9-running"))
    running = repository.claim_next("v9-running-worker")
    assert running is not None
    assert running.job_id == running_v9.job_id
    assert running.status == MonitoringAiJobStatus.RUNNING
    assert running.attempt_count == 1
    assert running.lease_owner == "v9-running-worker"

    queued_v9 = repository.create_or_get(v9_request("v9-queued"))
    assert queued_v9.status == MonitoringAiJobStatus.QUEUED

    # Startup prompt cutover exactly as main.py runs it: the retirement-audit
    # set preserves terminal v9 evidence while active v9 work is retired;
    # every v9 row is durably marked and never reused.
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version=v12_prompt,
        legacy_terminal_prompt_versions=(
            PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
        ),
    )
    assert changed == 2

    # Preserved terminal v9: status, failure evidence, retryable value,
    # timestamps, attempt lineage and candidate status/content stay frozen
    # while the row gains the immutable contract-retirement marker.
    preserved_completed = repository.get(PROJECT_ID, completed_v9.job_id)
    assert preserved_completed.status == MonitoringAiJobStatus.COMPLETED
    assert preserved_completed.failure_code == terminal_completed.failure_code
    assert preserved_completed.failure_message == (
        terminal_completed.failure_message
    )
    assert preserved_completed.retryable == terminal_completed.retryable
    assert preserved_completed.created_at == terminal_completed.created_at
    assert preserved_completed.updated_at == terminal_completed.updated_at
    assert preserved_completed.prompt_version == v9_prompt
    assert preserved_completed.attempt_count == 1
    assert preserved_completed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert preserved_completed.contract_retirement_reason != ""
    assert preserved_completed.contract_retired_at is not None
    preserved_completed_candidate = repository.candidates(
        PROJECT_ID,
        completed_v9.job_id,
    )[0]
    assert (
        preserved_completed_candidate.candidate_id
        == v9_candidate.candidate_id
    )
    assert preserved_completed_candidate.status == (
        MonitoringAiCandidateStatus.PROPOSED
    )
    assert preserved_completed_candidate.evidence == v9_candidate.evidence
    assert preserved_completed_candidate.structured_payload == (
        v9_candidate.structured_payload
    )
    assert preserved_completed_candidate.created_at == v9_candidate.created_at

    preserved_failed = repository.get(PROJECT_ID, failed_v9.job_id)
    assert preserved_failed.status == MonitoringAiJobStatus.FAILED
    assert preserved_failed.failure_code == "provider_timeout"
    assert preserved_failed.failure_message == "provider timed out"
    assert preserved_failed.retryable == terminal_failed.retryable
    assert preserved_failed.created_at == terminal_failed.created_at
    assert preserved_failed.updated_at == terminal_failed.updated_at
    assert preserved_failed.attempt_count == 1
    assert preserved_failed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert preserved_failed.contract_retired_at is not None
    assert repository.attempts(PROJECT_ID, failed_v9.job_id)[0]["outcome"] == (
        "provider_error"
    )

    # Preserved terminal v9 stays status-incompatible under the v12 contract
    # and is never selected by status/start.
    assert (
        service._prompt_version_is_status_compatible(
            preserved_completed,
            v12_prompt,
        )
        is False
    )
    assert (
        service._prompt_version_is_status_compatible(
            preserved_failed,
            v12_prompt,
        )
        is False
    )

    # The preserved failed v9 row keeps its provider evidence but is durably
    # retired: same-revision retry is refused and the row is not revived.
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            failed_v9.job_id,
            current_input_revision_sha256=failed_v9.input_revision_sha256,
        )
    still_failed = repository.get(PROJECT_ID, failed_v9.job_id)
    assert still_failed.status == MonitoringAiJobStatus.FAILED
    assert still_failed.failure_code == "provider_timeout"
    assert still_failed.failure_message == "provider timed out"
    assert still_failed.attempt_count == 1
    assert still_failed.contract_retirement_code == (
        "superseded_prompt_contract"
    )

    # The preserved completed v9 row is terminal and cannot be retried.
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="only failed, blocked or stale monitoring AI jobs can be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            completed_v9.job_id,
            current_input_revision_sha256=completed_v9.input_revision_sha256,
        )
    assert repository.get(PROJECT_ID, completed_v9.job_id).status == (
        MonitoringAiJobStatus.COMPLETED
    )

    # Every preserved or retired v9 row carries the durable retirement marker.
    assert preserved_completed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert preserved_completed.contract_retired_at is not None
    assert preserved_failed.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    assert preserved_failed.contract_retired_at is not None

    for retired_job in (queued_v9, running_v9):
        state = repository.get(PROJECT_ID, retired_job.job_id)
        assert state.status == MonitoringAiJobStatus.STALE_INPUT
        assert state.failure_code == "superseded_prompt_contract"
        assert state.lease_owner == ""
        assert state.lease_expires_at is None
        assert state.retryable is False
        assert state.contract_retirement_code == "superseded_prompt_contract"
        assert state.contract_retired_at is not None
    assert repository.get(PROJECT_ID, queued_v9.job_id).attempt_count == 0
    assert repository.get(PROJECT_ID, running_v9.job_id).attempt_count == 1

    # A late completion from the retired running v9 loses CAS and persists
    # zero candidates.
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="completion",
    ):
        repository.complete(
            running,
            owner="v9-running-worker",
            response_model=running.requested_model,
            raw_output={
                "candidates": [late_v9_candidate(running).model_dump(mode="json")]
            },
            candidates=(late_v9_candidate(running),),
        )
    assert repository.candidates(PROJECT_ID, running_v9.job_id) == ()

    # No retired v9 row can be claimed while only v9 rows exist: preserved
    # terminal rows are not claimable and active rows are already stale.
    assert repository.claim_next("v9-reclaim-worker") is None

    # The execution-level cutover creates a distinct v12 job on the same
    # input revision and selects it.
    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v9_ids = {
        completed_v9.job_id,
        failed_v9.job_id,
        queued_v9.job_id,
        running_v9.job_id,
    }
    v12_job = next(job for job in jobs if job.prompt_version == v12_prompt)
    assert v12_job.job_id not in v9_ids
    assert v12_job.status == MonitoringAiJobStatus.QUEUED
    assert v12_job.input_revision_sha256 == input_revision.revision_sha256
    assert restarted["topics"][0]["job"]["job_id"] == v12_job.job_id

    # No retired v9 job can be retried with the same revision, and none can
    # be claimed while the v12 job is eligible.
    for retired_job in (queued_v9, running_v9):
        with pytest.raises(
            MonitoringAiStateConflictError,
            match="cannot be retried",
        ):
            repository.retry_terminal(
                PROJECT_ID,
                retired_job.job_id,
                current_input_revision_sha256=input_revision.revision_sha256,
            )
        assert repository.get(PROJECT_ID, retired_job.job_id).status == (
            MonitoringAiJobStatus.STALE_INPUT
        )

    result = ai_service.run_next("v12-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v12_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v12_prompt
    assert result.job.attempt_count == 1
    assert len(repository.candidates(PROJECT_ID, v12_job.job_id)) == 1
    assert repository.candidates(PROJECT_ID, v12_job.job_id)[0].status == (
        MonitoringAiCandidateStatus.PROPOSED
    )

    # v9 ids, attempt counts and candidates stay frozen after v12 completes.
    assert repository.get(PROJECT_ID, completed_v9.job_id).status == (
        MonitoringAiJobStatus.COMPLETED
    )
    assert repository.get(PROJECT_ID, completed_v9.job_id).attempt_count == 1
    assert repository.get(PROJECT_ID, failed_v9.job_id).status == (
        MonitoringAiJobStatus.FAILED
    )
    assert repository.get(PROJECT_ID, failed_v9.job_id).attempt_count == 1
    assert repository.get(PROJECT_ID, queued_v9.job_id).attempt_count == 0
    assert repository.get(PROJECT_ID, running_v9.job_id).attempt_count == 1
    preserved_candidate_after = repository.candidates(
        PROJECT_ID,
        completed_v9.job_id,
    )[0]
    assert preserved_candidate_after.candidate_id == v9_candidate.candidate_id
    assert preserved_candidate_after.status == (
        MonitoringAiCandidateStatus.PROPOSED
    )
    assert repository.candidates(PROJECT_ID, queued_v9.job_id) == ()
    assert repository.candidates(PROJECT_ID, running_v9.job_id) == ()


class InvalidProtocolClauseProvider:
    """Product provider that always returns a protocol candidate with the
    wrong candidate type, which deterministically fails protocol clause
    validation on both the initial and the controlled-repair provider call."""

    provider_name = "test-product-ai"
    model_name = "test-product-model"
    expected_response_model = "test-product-model"
    response_model = "test-product-model"
    transport_name = "openai_compatible"

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        input_payload = envelope.payload.get("input_payload")
        if input_payload is None:
            input_payload = envelope.payload["original_task"]["input_payload"]
        revision_hash = envelope.payload.get("input_revision_sha256")
        if revision_hash is None:
            revision_hash = envelope.payload["original_task"][
                "input_revision_sha256"
            ]
        return {
            "schema_version": "monitoring_ai_v1",
            "task_id": envelope.task_id,
            "task_type": "protocol_clause_structuring",
            "input_revision_sha256": revision_hash,
            "candidates": [
                {
                    "candidate_type": "field_mapping",
                    "title": "无效条款候选",
                    "text": "该输出类型不属于条款结构化合同。",
                    "structured_payload": {"clause_id": "clause-invalid-v9"},
                    "claims": [],
                    "evidence": [],
                }
            ],
        }


def test_v9_production_key_invalid_output_survives_v10_submission(
    tmp_path: Path,
) -> None:
    """Exact production business key: a failed v9 job with
    invalid_ai_output and an initial+repair response lineage survives both
    the v10 startup cutover and the same-key v10 submission, keeping status,
    failure evidence, timestamps, attempt lineage and zero candidates while
    staying status-incompatible, non-retryable and non-reusable."""
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    input_revision = prepared["packet"].input_revision
    business_key = prepared["business_key"]
    v9_prompt = "monitoring-protocol-clause-structuring-v9"
    v10_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]

    failed_v9 = repository.create_or_get(
        MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=input_revision,
            input_payload=payload,
            prompt_version=v9_prompt,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=business_key,
        )
    )
    invalid_provider = InvalidProtocolClauseProvider()
    failing_service = MonitoringAiService(
        repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider=invalid_provider.provider_name,
            model=invalid_provider.model_name,
            env={
                "WORKBENCH_AI_PROVIDER": invalid_provider.provider_name,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": invalid_provider.model_name,
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": (
                    invalid_provider.model_name
                ),
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: invalid_provider,
    )
    failed_result = failing_service.run_next("v9-invalid-output-worker")
    assert failed_result.processed is True
    assert failed_result.job is not None
    assert failed_result.job.job_id == failed_v9.job_id
    assert failed_result.job.status == MonitoringAiJobStatus.FAILED
    assert failed_result.job.failure_code == "invalid_ai_output"
    assert failed_result.job.attempt_count == 1
    assert "remained invalid after one controlled repair" in (
        failed_result.job.failure_message
    )
    assert repository.candidates(PROJECT_ID, failed_v9.job_id) == ()

    # Initial + controlled-repair response lineage is recorded on the single
    # attempt: both request envelopes and both provider outputs.
    attempts = repository.attempts(PROJECT_ID, failed_v9.job_id)
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "invalid_output"
    assert attempts[0]["failure_code"] == "invalid_ai_output"
    assert "envelope" in attempts[0]["request"]
    assert "repair_envelope" in attempts[0]["request"]
    assert len(attempts[0]["response"]["provider_outputs"]) == 2

    # Startup prompt cutover preserves the terminal v9 row and marks it.
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version=v10_prompt,
        legacy_terminal_prompt_versions=(
            PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
        ),
    )
    assert changed == 0
    preserved = repository.get(PROJECT_ID, failed_v9.job_id)
    assert preserved.status == MonitoringAiJobStatus.FAILED
    assert preserved.failure_code == "invalid_ai_output"
    assert preserved.retryable is False
    preserved_updated_at = preserved.updated_at
    assert preserved.contract_retirement_code == "superseded_prompt_contract"

    # The exact-key v10 submission must not destroy the preserved evidence.
    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v10_job = next(job for job in jobs if job.prompt_version == v10_prompt)
    assert v10_job.job_id != failed_v9.job_id
    assert v10_job.status == MonitoringAiJobStatus.QUEUED
    assert v10_job.input_revision_sha256 == input_revision.revision_sha256
    assert v10_job.business_key == business_key
    assert restarted["topics"][0]["job"]["job_id"] == v10_job.job_id

    still_preserved = repository.get(PROJECT_ID, failed_v9.job_id)
    assert still_preserved.status == MonitoringAiJobStatus.FAILED
    assert still_preserved.failure_code == "invalid_ai_output"
    assert "remained invalid after one controlled repair" in (
        still_preserved.failure_message
    )
    assert still_preserved.retryable is False
    assert still_preserved.created_at == preserved.created_at
    assert still_preserved.updated_at == preserved_updated_at
    assert still_preserved.attempt_count == 1
    assert still_preserved.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    still_attempts = repository.attempts(PROJECT_ID, failed_v9.job_id)
    assert len(still_attempts) == 1
    assert still_attempts[0]["outcome"] == "invalid_output"
    assert "repair_envelope" in still_attempts[0]["request"]
    assert len(still_attempts[0]["response"]["provider_outputs"]) == 2
    assert repository.candidates(PROJECT_ID, failed_v9.job_id) == ()
    assert (
        service._prompt_version_is_status_compatible(
            still_preserved,
            v10_prompt,
        )
        is False
    )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            failed_v9.job_id,
            current_input_revision_sha256=input_revision.revision_sha256,
        )

    result = ai_service.run_next("v10-invalid-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v10_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v10_prompt
    assert len(repository.candidates(PROJECT_ID, v10_job.job_id)) == 1


def test_v10_production_key_invalid_output_survives_v12_submission(
    tmp_path: Path,
) -> None:
    """Frozen v10-to-v12 same-business-key history preservation.

    A terminal v10 row shaped like the frozen canary (failed/
    invalid_ai_output/retryable=0, one attempt with initial+repair
    request lineage and two provider outputs, zero candidates, with the
    recorded candidate-2 one-family failure message) survives both the v12
    startup cutover and the same-key v12 submission with every
    status/failure/timestamp/attempt-hash field unchanged while receiving
    the immutable contract-retirement marker, and the same-key v12 job
    gets a distinct job id and prompt identity. The preserved v10 row is
    never status-compatible, retryable or reusable under v12.

    The attempt request/response payloads, their computed hashes and the
    timestamps are synthetic repository state reconstructed for the test:
    they are NOT a replay of the frozen runtime payloads (whose request/
    response SHAs b034…/def009… and wall-clock timestamps are not
    reproducible offline), and the assertions prove exact preservation of
    whatever was recorded, not identity with the runtime values."""
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    input_revision = prepared["packet"].input_revision
    business_key = prepared["business_key"]
    v10_prompt = "monitoring-protocol-clause-structuring-v10"
    v12_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]
    assert v12_prompt == "monitoring-protocol-clause-structuring-v12"
    assert v10_prompt not in PROTOCOL_STATUS_LEGACY_PROMPT_VERSIONS
    assert v10_prompt in PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
    v9_prompt = "monitoring-protocol-clause-structuring-v9"
    assert v9_prompt in PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS

    frozen_v10 = repository.create_or_get(
        MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=input_revision,
            input_payload=payload,
            prompt_version=v10_prompt,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=business_key,
        )
    )
    claimed = repository.claim_next("v10-frozen-worker")
    assert claimed is not None
    assert claimed.job_id == frozen_v10.job_id
    canary_failure = (
        "protocol candidate validation failed:\n"
        "candidate 2 (受试者无法在访视窗内到中心时可重新安排访视): "
        "visit protocol candidate must contain exactly one visit action "
        "family"
    )
    request_payload = {
        "envelope": {"prompt_version": v10_prompt},
        "repair_envelope": {
            "prompt_version": f"{v10_prompt}:json-repair-1"
        },
    }
    response_payload = {
        "provider_outputs": [
            {"attempt": 1, "persisted_candidates": 0},
            {"attempt": 2, "persisted_candidates": 0},
        ]
    }
    frozen_request_sha = content_sha256(request_payload)
    frozen_response_sha = content_sha256(response_payload)
    repository.record_attempt(
        claimed,
        owner="v10-frozen-worker",
        request_payload=request_payload,
        response_payload=response_payload,
        response_model="test-product-model",
        outcome="invalid_output",
        failure_code="invalid_ai_output",
        failure_message=canary_failure,
    )
    frozen = repository.fail(
        claimed,
        owner="v10-frozen-worker",
        failure_code="invalid_ai_output",
        failure_message=canary_failure,
        retryable=False,
    )
    assert frozen.status == MonitoringAiJobStatus.FAILED
    assert frozen.failure_code == "invalid_ai_output"
    assert frozen.retryable is False
    assert frozen.attempt_count == 1
    assert repository.candidates(PROJECT_ID, frozen_v10.job_id) == ()
    frozen_created_at = frozen.created_at
    frozen_updated_at = frozen.updated_at
    attempts = repository.attempts(PROJECT_ID, frozen_v10.job_id)
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "invalid_output"
    assert attempts[0]["failure_code"] == "invalid_ai_output"
    assert attempts[0]["request_sha256"] == frozen_request_sha
    assert attempts[0]["response_sha256"] == frozen_response_sha
    assert len(attempts[0]["response"]["provider_outputs"]) == 2
    frozen_attempt_id = attempts[0]["attempt_id"]

    # Startup prompt cutover preserves the frozen v10 row and marks it.
    changed = repository.supersede_prompt_versions_except(
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        current_prompt_version=v12_prompt,
        legacy_terminal_prompt_versions=(
            PROTOCOL_RETIREMENT_AUDIT_PROMPT_VERSIONS
        ),
    )
    assert changed == 0
    preserved = repository.get(PROJECT_ID, frozen_v10.job_id)
    assert preserved.status == MonitoringAiJobStatus.FAILED
    assert preserved.failure_code == "invalid_ai_output"
    assert preserved.retryable is False
    assert preserved.prompt_version == v10_prompt
    assert preserved.created_at == frozen_created_at
    assert preserved.updated_at == frozen_updated_at
    assert preserved.attempt_count == 1
    assert preserved.contract_retirement_code == "superseded_prompt_contract"
    assert preserved.contract_retired_at is not None
    assert "candidate 2 (受试者无法在访视窗内到中心时可重新安排访视):" in (
        preserved.failure_message
    )
    assert "exactly one visit action family" in preserved.failure_message
    assert repository.candidates(PROJECT_ID, frozen_v10.job_id) == ()

    # The exact-key v12 submission creates a distinct job and never touches
    # the preserved v10 row.
    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v12_job = next(job for job in jobs if job.prompt_version == v12_prompt)
    assert v12_job.job_id != frozen_v10.job_id
    assert v12_job.status == MonitoringAiJobStatus.QUEUED
    assert v12_job.input_revision_sha256 == input_revision.revision_sha256
    assert v12_job.business_key == business_key
    assert restarted["topics"][0]["job"]["job_id"] == v12_job.job_id

    still_preserved = repository.get(PROJECT_ID, frozen_v10.job_id)
    assert still_preserved.status == MonitoringAiJobStatus.FAILED
    assert still_preserved.failure_code == "invalid_ai_output"
    assert still_preserved.retryable is False
    assert still_preserved.created_at == frozen_created_at
    assert still_preserved.updated_at == frozen_updated_at
    assert still_preserved.attempt_count == 1
    assert still_preserved.contract_retirement_code == (
        "superseded_prompt_contract"
    )
    still_attempts = repository.attempts(PROJECT_ID, frozen_v10.job_id)
    assert len(still_attempts) == 1
    assert still_attempts[0]["attempt_id"] == frozen_attempt_id
    assert still_attempts[0]["request_sha256"] == frozen_request_sha
    assert still_attempts[0]["response_sha256"] == frozen_response_sha
    assert len(still_attempts[0]["response"]["provider_outputs"]) == 2
    assert repository.candidates(PROJECT_ID, frozen_v10.job_id) == ()
    assert (
        service._prompt_version_is_status_compatible(
            still_preserved,
            v12_prompt,
        )
        is False
    )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            frozen_v10.job_id,
            current_input_revision_sha256=input_revision.revision_sha256,
        )

    result = ai_service.run_next("v12-frozen-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v12_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v12_prompt
    assert len(repository.candidates(PROJECT_ID, v12_job.job_id)) == 1
    # The frozen v10 row stays untouched after the v12 job completes.
    final = repository.get(PROJECT_ID, frozen_v10.job_id)
    assert final.status == MonitoringAiJobStatus.FAILED
    assert final.failure_code == "invalid_ai_output"
    assert final.updated_at == frozen_updated_at
    assert final.attempt_count == 1
    assert final.contract_retirement_code == "superseded_prompt_contract"
    assert repository.candidates(PROJECT_ID, frozen_v10.job_id) == ()


def test_v9_blocked_production_key_is_fail_closed_by_v10_submission(
    tmp_path: Path,
) -> None:
    """A blocked v9 job holding the exact production prepared business key
    is retired by the deterministic v10 submission: it becomes stale with a
    superseded contract marker, loses retryability and cannot be claimed,
    while a distinct v10 job is selected and completed."""
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    payload = service._input_payload(version, topic, prepared)
    input_revision = prepared["packet"].input_revision
    business_key = prepared["business_key"]
    v9_prompt = "monitoring-protocol-clause-structuring-v9"
    v10_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]

    blocked_v9 = ai_service.submit_task(
        project_id=PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=input_revision,
        input_payload=payload,
        business_key=business_key,
        prompt_version=v9_prompt,
    )
    assert blocked_v9.status == MonitoringAiJobStatus.QUEUED
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE monitoring_ai_jobs SET status = ? WHERE job_id = ?",
            (
                MonitoringAiJobStatus.BLOCKED.value,
                blocked_v9.job_id,
            ),
        )
    assert repository.get(PROJECT_ID, blocked_v9.job_id).status == (
        MonitoringAiJobStatus.BLOCKED
    )
    # A blocked row is never claimable even before the cutover.
    assert repository.claim_next("pre-cutover-worker") is None

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v10_job = next(job for job in jobs if job.prompt_version == v10_prompt)
    assert v10_job.job_id != blocked_v9.job_id
    assert v10_job.status == MonitoringAiJobStatus.QUEUED
    assert v10_job.business_key == business_key
    assert restarted["topics"][0]["job"]["job_id"] == v10_job.job_id

    retired = repository.get(PROJECT_ID, blocked_v9.job_id)
    assert retired.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired.failure_code == "superseded_job_contract"
    assert retired.retryable is False
    assert retired.lease_owner == ""
    assert retired.lease_expires_at is None
    assert retired.contract_retirement_code == "superseded_job_contract"
    assert retired.contract_retired_at is not None
    assert retired.attempt_count == 0
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="superseded contract cannot be retried",
    ):
        repository.retry_terminal(
            PROJECT_ID,
            blocked_v9.job_id,
            current_input_revision_sha256=input_revision.revision_sha256,
        )

    result = ai_service.run_next("v10-blocked-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v10_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v10_prompt
    assert repository.candidates(PROJECT_ID, blocked_v9.job_id) == ()
    assert repository.claim_next("post-cutover-worker") is None


def test_v9_exact_business_key_active_jobs_retired_by_v10_submission(
    tmp_path: Path,
) -> None:
    """A queued v9 job holding the exact production prepared business key is
    retired by the deterministic v10 submission, and a running v9 job with a
    legacy workflow is retired by the contract gate. Both are durably marked,
    never claimable or retryable, while a distinct v10 job is completed.
    """
    service, repository, ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    input_revision = prepared["packet"].input_revision
    payload = service._input_payload(version, topic, prepared)
    v9_prompt = "monitoring-protocol-clause-structuring-v9"
    v10_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]

    def v9_request(business_key: str, *, workflow: str) -> MonitoringAiJobCreate:
        payload_with_workflow = {
            **payload,
            "context": {**payload["context"], "workflow": workflow},
        }
        return MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=input_revision,
            input_payload=payload_with_workflow,
            prompt_version=v9_prompt,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=business_key,
        )

    running_v9 = repository.create_or_get(
        v9_request(
            f"{prepared['business_key']}:v9-running",
            workflow="monitoring_protocol_preparation_v1",
        )
    )
    running = repository.claim_next("v9-running-worker")
    assert running is not None
    assert running.job_id == running_v9.job_id
    assert running.status == MonitoringAiJobStatus.RUNNING

    queued_v9 = repository.create_or_get(
        v9_request(
            prepared["business_key"],
            workflow=PROTOCOL_PREPARATION_CONTRACT_VERSION,
        )
    )
    assert queued_v9.status == MonitoringAiJobStatus.QUEUED

    restarted = service.start(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        topic_ids=(topic.topic_id,),
    )
    jobs = repository.list_jobs(
        PROJECT_ID,
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING.value,
        business_key_prefix=PROTOCOL_PREPARATION_BUSINESS_KEY_PREFIX,
    )
    v10_job = next(job for job in jobs if job.prompt_version == v10_prompt)
    assert v10_job.job_id not in {queued_v9.job_id, running_v9.job_id}
    assert v10_job.input_revision_sha256 == input_revision.revision_sha256
    assert v10_job.status == MonitoringAiJobStatus.QUEUED
    assert restarted["topics"][0]["job"]["job_id"] == v10_job.job_id

    retired_queued = repository.get(PROJECT_ID, queued_v9.job_id)
    assert retired_queued.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired_queued.failure_code == "superseded_job_contract"
    assert retired_queued.contract_retirement_code == "superseded_job_contract"
    assert retired_queued.contract_retirement_reason
    assert retired_queued.contract_retired_at is not None
    assert retired_queued.attempt_count == 0

    retired_running = repository.get(PROJECT_ID, running_v9.job_id)
    assert retired_running.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired_running.failure_code == "superseded_workflow_contract"
    assert retired_running.contract_retirement_code == (
        "superseded_workflow_contract"
    )
    assert retired_running.lease_owner == ""
    assert retired_running.lease_expires_at is None
    assert retired_running.attempt_count == 1

    for retired_job in (queued_v9, running_v9):
        with pytest.raises(
            MonitoringAiStateConflictError,
            match="cannot be retried",
        ):
            repository.retry_terminal(
                PROJECT_ID,
                retired_job.job_id,
                current_input_revision_sha256=input_revision.revision_sha256,
            )
        assert repository.get(PROJECT_ID, retired_job.job_id).status == (
            MonitoringAiJobStatus.STALE_INPUT
        )

    result = ai_service.run_next("v10-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.job_id == v10_job.job_id
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.prompt_version == v10_prompt
    assert len(repository.candidates(PROJECT_ID, v10_job.job_id)) == 1
    assert repository.get(PROJECT_ID, queued_v9.job_id).attempt_count == 0
    assert repository.get(PROJECT_ID, running_v9.job_id).attempt_count == 1


def test_retired_protocol_identity_resubmission_fails_loudly(
    tmp_path: Path,
) -> None:
    """A deterministic submission that resolves to a permanently retired
    identity fails loudly inside the preparation start flow and does not
    revive the retired row.
    """
    service, repository, _ai_service, _provider, version, _wakes = _service(
        tmp_path
    )
    topic = service.topic_by_id["visit_window_and_order"]
    prepared = service._prepare_topic(version, topic)
    input_revision = prepared["packet"].input_revision
    payload = service._input_payload(version, topic, prepared)
    v12_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
    ]

    def request(prompt_version: str) -> MonitoringAiJobCreate:
        return MonitoringAiJobCreate(
            project_id=PROJECT_ID,
            task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
            input_revision=input_revision,
            input_payload=payload,
            prompt_version=prompt_version,
            profile_id="independent-ai-test",
            provider="test-product-ai",
            requested_model="test-product-model",
            max_attempts=2,
            business_key=prepared["business_key"],
        )

    current_v12 = repository.create_or_get(request(v12_prompt))
    newer = repository.create_or_get(
        request("monitoring-protocol-clause-structuring-v13")
    )
    assert newer.job_id != current_v12.job_id
    changed = repository.supersede_business_key_except(
        PROJECT_ID,
        business_key=prepared["business_key"],
        current_job_id=newer.job_id,
        reason="newer contract deployed",
    )
    assert changed == 1
    retired = repository.get(PROJECT_ID, current_v12.job_id)
    assert retired.status == MonitoringAiJobStatus.STALE_INPUT
    assert retired.failure_code == "superseded_job_contract"
    assert retired.contract_retirement_code == "superseded_job_contract"
    assert retired.contract_retired_at is not None

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="cannot be retried",
    ):
        service.start(
            project_id=PROJECT_ID,
            protocol_version_id=version.protocol_version_id,
            topic_ids=(topic.topic_id,),
        )
    after = repository.get(PROJECT_ID, current_v12.job_id)
    assert after.status == MonitoringAiJobStatus.STALE_INPUT
    assert after.failure_code == "superseded_job_contract"
    assert after.attempt_count == 0
    assert after.contract_retirement_code == "superseded_job_contract"
    assert repository.candidates(PROJECT_ID, current_v12.job_id) == ()
