from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence

import pytest
from pydantic import ValidationError

import services.api.app.monitoring_ai_service as monitoring_ai_service_module
from services.api.app.ai_gateway import AiPromptEnvelope, AiTaskType
from services.api.app.monitoring_ai_contracts import (
    MONITORING_AI_SCHEMA_VERSION,
    MonitoringAiCandidateStatus,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_deterministic_metadata_mapping import (
    DETERMINISTIC_METADATA_MAPPING_VERSION,
    DETERMINISTIC_METADATA_MODEL,
    DETERMINISTIC_METADATA_PROVIDER,
    deterministic_metadata_decision,
)
from services.api.app.monitoring_ai_service import (
    AI_TASK_TYPE_BY_MONITORING_TASK,
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
    monitoring_revision_with_field_profile,
    resolve_monitoring_ai_runtime,
)
from services.api.app.monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
)
from services.api.app.monitoring_mapping_semantic_quality import (
    ROLE_CATALOG_VERSION,
    RULE_CATALOG_VERSION,
)


SOURCE_HASH = "a" * 64
INPUT_HASH = "b" * 64
PROFILE_HASH = "c" * 64


class MutableClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self._value += timedelta(**kwargs)


class FakeProvider:
    provider_name = "test-provider"
    model_name = "test-model"
    expected_response_model = "test-model"
    transport_name = "openai_compatible"

    def __init__(
        self,
        builders: List[Callable[[AiPromptEnvelope], Dict[str, Any]]],
        *,
        response_model: str = "test-model",
        before_return: Optional[Callable[[], None]] = None,
    ):
        self.builders = list(builders)
        self.response_model = response_model
        self.before_return = before_return
        self.envelopes: List[AiPromptEnvelope] = []

    def run(self, envelope: AiPromptEnvelope) -> Dict[str, Any]:
        self.envelopes.append(envelope)
        index = min(len(self.envelopes) - 1, len(self.builders) - 1)
        result = self.builders[index](envelope)
        if self.before_return is not None:
            self.before_return()
        return result


def _runtime() -> MonitoringAiRuntimeBinding:
    return MonitoringAiRuntimeBinding(
        profile_id="independent-ai-test",
        provider="test-provider",
        model="test-model",
        env={
            "WORKBENCH_AI_PROVIDER": "test-provider",
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
            "WORKBENCH_AI_API_KEY": "test-key",
            "WORKBENCH_AI_MODEL": "test-model",
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "test-model",
            "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
        },
    )


def _revision(suffix: str = "001") -> MonitoringAiInputRevision:
    return MonitoringAiInputRevision(
        project_id="project-alpha",
        batch_revision=f"batch-{suffix}",
        mapping_revision=f"mapping-{suffix}",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )


def _field_profile(field_count: int = 8) -> Dict[str, Any]:
    return {
        "schema_version": "monitoring_ai_field_profile_v1",
        "batch_id": "batch-001",
        "project_id": "project-alpha",
        "batch_revision": 1,
        "mapping_revision": "mapping-001",
        "expected_domains": ["AE", "CM", "LB"],
        "source_bindings": [
            {
                "source_entry_id": "source-listing",
                "source_content_sha256": SOURCE_HASH,
            }
        ],
        "source_sha256s": [SOURCE_HASH],
        "row_count": 147,
        "input_sha256": INPUT_HASH,
        "fields": [
            {
                "domain": "LB",
                "field": f"LB_FIELD_{index:02d}",
                "total_rows": 147,
                "non_empty_count": 140,
                "null_rate": 0.0476,
                "inferred_type": "string",
                "unique_value_count": 25,
                "top_values": [],
                "representative_values": [f"value-{index}"],
                "anomaly_examples": [],
            }
            for index in range(field_count)
        ],
        "profile_sha256": PROFILE_HASH,
    }


def _my008_scale_field_profile() -> Dict[str, Any]:
    fields: List[Dict[str, Any]] = []
    domain_sizes = {
        f"D{domain_index:02d}": 46 if domain_index < 14 else 45
        for domain_index in range(32)
    }
    for domain in reversed(tuple(domain_sizes)):
        for field_index in reversed(range(domain_sizes[domain])):
            fields.append(
                {
                    "domain": domain,
                    "field": f"{domain}_FIELD_{field_index:03d}",
                    "total_rows": 8699,
                    "non_empty_count": 8600 - field_index,
                    "null_rate": round(
                        (99 + field_index) / 8699,
                        6,
                    ),
                    "inferred_type": "string",
                    "unique_value_count": 100 + field_index,
                    "top_values": [],
                    "representative_values": [f"{domain}-value-{field_index}"],
                    "anomaly_examples": [],
                }
            )
    assert len(fields) == 1454
    return {
        "schema_version": "monitoring_ai_field_profile_v1",
        "batch_id": "MY008-20250417",
        "project_id": "project-alpha",
        "batch_revision": 1,
        "mapping_revision": "mapping-my008-20250417",
        "expected_domains": sorted(domain_sizes),
        "source_bindings": [
            {
                "source_entry_id": "source-listing",
                "source_content_sha256": SOURCE_HASH,
            }
        ],
        "source_sha256s": [SOURCE_HASH],
        "row_count": 8699,
        "input_sha256": INPUT_HASH,
        "fields": fields,
        "profile_sha256": PROFILE_HASH,
    }


def _nonmapping_input_payload(**context: Any) -> Dict[str, Any]:
    return {
        **context,
        "evidence_packet": [
            {
                "evidence_id": f"evidence-{index}",
                "source_entry_id": "source-listing",
                "source_content_sha256": SOURCE_HASH,
                "locator": f"listing:test:row:{index}",
                "quote": f"授权来源中的原始证据 {index}。",
                "raw_fields": {
                    "evidence_kind": "original_data",
                    "fields": [
                        {
                            "field": "DOMAIN",
                            "value": "AE" if index == 1 else "CM",
                        }
                    ],
                },
            }
            for index in range(1, 4)
        ],
    }


def _valid_output(
    envelope: AiPromptEnvelope,
    *,
    candidate_count: int = 1,
) -> Dict[str, Any]:
    revision_hash = envelope.payload.get("input_revision_sha256")
    if revision_hash is None:
        revision_hash = envelope.payload["original_task"]["input_revision_sha256"]
    source = envelope.payload["authorized_source_pairs"][0]
    task_type = MonitoringAiTaskType(
        envelope.payload["monitoring_task_type"]
        if "monitoring_task_type" in envelope.payload
        else envelope.payload["original_task"]["monitoring_task_type"]
    )
    original_payload = envelope.payload.get("input_payload")
    if original_payload is None:
        original_payload = envelope.payload["original_task"]["input_payload"]
    candidates: List[Dict[str, Any]] = []
    if task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
        fields = original_payload["field_profile"]["fields"]
        evidence = []
        field_mappings = []
        for index, field in enumerate(fields, start=1):
            evidence_id = f"evidence-{index}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_entry_id": source["source_entry_id"],
                    "source_content_sha256": source["source_content_sha256"],
                    "locator": (f"profile://{field['domain']}/{field['field']}"),
                    "quote": "",
                    "raw_fields": {
                        "domain": field["domain"],
                        "field": field["field"],
                        "inferred_type": field["inferred_type"],
                    },
                }
            )
            field_mappings.append(
                {
                    "domain": field["domain"],
                    "source_field": field["field"],
                    "recommended_role": "lab_result_candidate",
                    "field_kind": "source_collected",
                    "confidence": 0.82,
                    "uncertainty": "仍需核对单位和参考范围字段。",
                    "user_action": "请医学经理确认字段角色。",
                    "related_fields": [],
                    "evidence_ids": [evidence_id],
                }
            )
        candidates.append(
            {
                "candidate_type": "listing_field_mapping_set",
                "title": "完整字段语义映射候选",
                "text": "完整覆盖冻结批次字段画像，供医学经理确认。",
                "structured_payload": {
                    "field_mappings": field_mappings,
                },
                "claims": [
                    {
                        "claim_id": "claim-mapping-set",
                        "kind": "recommendation",
                        "text": "字段角色仍需结合项目数据字典确认。",
                        "confidence": 0.82,
                        "uncertainty": "当前仅使用完整字段画像。",
                        "user_action": "请逐项确认或修订。",
                        "evidence_ids": [evidence[0]["evidence_id"]],
                    }
                ],
                "evidence": evidence,
            }
        )
    else:
        resolved_count = (
            candidate_count
            if task_type
            in (
                MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
                MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
            )
            else 1
        )
        protocol_fact_type = "safety_assessment"
        if task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING:
            context = original_payload.get("context")
            if isinstance(context, dict):
                allowed_fact_types = context.get("candidate_fact_types")
                if isinstance(allowed_fact_types, list) and allowed_fact_types:
                    protocol_fact_type = str(allowed_fact_types[0]).strip()
        for index in range(1, resolved_count + 1):
            evidence_id = f"evidence-{index}"
            candidate_type, structured_payload = _task_payload(
                task_type,
                index,
                evidence_id,
                fact_type=protocol_fact_type,
            )
            if task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS:
                structured_payload["evidence_ids"] = [
                    "evidence-1",
                    "evidence-2",
                ]
            candidates.append(
                {
                    "candidate_type": candidate_type,
                    "title": f"监查候选 {index}",
                    "text": "基于授权证据提出，需医学经理复核。",
                    "structured_payload": structured_payload,
                    "claims": [
                        {
                            "claim_id": f"claim-{index}",
                            "kind": "recommendation",
                            "text": "该候选需要结合完整项目上下文复核。",
                            "confidence": 0.82,
                            "uncertainty": "尚未获得医学经理最终判断。",
                            "user_action": "请确认或修订候选。",
                            "evidence_ids": [evidence_id],
                        }
                    ],
                }
            )
    return {
        "schema_version": MONITORING_AI_SCHEMA_VERSION,
        "task_id": envelope.task_id,
        "task_type": task_type.value,
        "input_revision_sha256": revision_hash,
        "candidates": candidates,
    }


def _task_payload(
    task_type: MonitoringAiTaskType,
    index: int,
    evidence_id: str,
    *,
    fact_type: str = "safety_assessment",
) -> tuple[str, Dict[str, Any]]:
    if task_type == MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING:
        return (
            "protocol_clause_structure",
            {
                "clause_id": f"clause-{index}",
                "fact_type": fact_type,
                "subject_scope": "所有已随机受试者",
                "conditions": ["满足方案规定条件"],
                "time_windows": ["访视窗内"],
                "thresholds": [],
                "exceptions": [],
                "required_actions": ["医学复核"],
                "evidence_ids": [evidence_id],
            },
        )
    if task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS:
        return (
            "cross_table_clue",
            {
                "subject_id": "S001",
                "domains": ["AE", "CM"],
                "observations": ["AE与合并用药日期接近"],
                "temporal_relationships": ["时间相关但不代表因果"],
                "data_gaps": ["缺少停药后转归"],
                "recommended_review": "核对AE、CM和访视原始记录。",
                "evidence_ids": [evidence_id],
            },
        )
    if task_type == MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY:
        return (
            "risk_evidence_summary",
            {
                "risk_id": f"risk-{index}",
                "facts": ["原始记录存在时间差异"],
                "inferences": ["可能需要进一步核查"],
                "data_gaps": ["缺少研究者解释"],
                "recommended_actions": ["核对原始数据"],
                "evidence_ids": [evidence_id],
            },
        )
    if task_type == MonitoringAiTaskType.RISK_QUESTION_ANSWER:
        return (
            "risk_question_answer",
            {
                "question": "该风险项的原始依据是什么？",
                "answer": "授权来源显示记录存在差异。",
                "evidence_limitations": ["尚未获得研究者解释"],
                "follow_up_questions": ["请确认记录日期。"],
                "evidence_ids": [evidence_id],
            },
        )
    mode = "query" if index % 2 else "explanation"
    return (
        "query_candidate" if mode == "query" else "explanation_candidate",
        {
            "mode": mode,
            "observation": "原始记录存在需要澄清的差异。",
            "request_or_explanation": "请核对并补充说明。",
            "requested_follow_up": "请提供更正或医学解释。",
            "evidence_ids": [evidence_id],
        },
    )


def _service(
    tmp_path: Path,
    provider: FakeProvider,
    *,
    clock: Optional[MutableClock] = None,
    lease_seconds: int = 300,
    runtime_resolver: Callable[[], MonitoringAiRuntimeBinding] = _runtime,
    current_revision_resolver: Optional[Callable[[Any], str]] = None,
) -> MonitoringAiService:
    repository = MonitoringAiRepository(
        tmp_path / "monitoring-ai.sqlite3",
        lease_seconds=lease_seconds,
        clock=clock or MutableClock(),
    )
    return MonitoringAiService(
        repository,
        runtime_resolver=runtime_resolver,
        provider_factory=lambda _env: provider,
        current_revision_resolver=current_revision_resolver,
    )


def test_normal_output_preserves_all_field_profiles_and_response_identity(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(field_count=8),
    )

    result = service.run_next("worker-a")

    assert result.processed is True
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.response_model == "test-model"
    assert len(service.repository.candidates(job.project_id, job.job_id)) == 1
    sent_fields = provider.envelopes[0].payload["input_payload"]["field_profile"][
        "fields"
    ]
    assert len(sent_fields) == 8
    assert sent_fields[-1]["field"] == "LB_FIELD_07"
    prompt = provider.envelopes[0]
    assert prompt.payload["candidate_types"] == ["listing_field_mapping_set"]
    assert prompt.payload["scientific_boundary"]["source_record"].endswith(
        "FIELD_MAPPING_SCIENTIFIC_BOUNDARY.md"
    )
    assert prompt.prompt_version == "monitoring-listing-field-mapping-v16"
    assert "CM只表示非试验用药" in prompt.system_prompt
    assert "relationships只提供同域同行的聚合统计" in prompt.system_prompt
    assert "则不得标为普通source_collected" in prompt.system_prompt
    assert "required_output_field_names" in prompt.system_prompt
    assert sent_fields[-1]["field"] in prompt.payload["candidate_count_contract"]
    assert prompt.payload["input_payload"]["field_profile"][
        "required_output_field_names"
    ] == [item["field"] for item in sent_fields]
    assert prompt.payload["input_payload"]["field_profile"][
        "mapping_contract_versions"
    ] == {
        "deterministic_metadata_mapping": (
            DETERMINISTIC_METADATA_MAPPING_VERSION
        ),
        "role_catalog": ROLE_CATALOG_VERSION,
        "semantic_rules": RULE_CATALOG_VERSION,
    }
    assert set(prompt.payload["field_relationship_contract"]) == {
        "term_code_pair",
        "site_identity_pair",
        "visit_identity_pair",
        "value_unit_pair",
        "performed_reason_pair",
    }
    assert "不等于中心主数据已经确认" in prompt.payload[
        "field_relationship_contract"
    ]["site_identity_pair"]
    assert "不得把OID直接翻译为访视名称" in prompt.payload[
        "field_relationship_contract"
    ]["visit_identity_pair"]
    assert (
        "field_mappings"
        in prompt.payload["output_schema"]["candidates"][0]["structured_payload"]
    )
    assert "claims" not in prompt.payload["output_schema"]["candidates"][0]
    assert "evidence" not in prompt.payload["output_schema"]["candidates"][0]
    assert prompt.max_output_tokens == 12_000


def test_provider_confidences_reject_boolean_values() -> None:
    with pytest.raises(ValidationError):
        monitoring_ai_service_module._ProviderClaim.model_validate(
            {
                "claim_id": "claim-bool-confidence",
                "kind": "recommendation",
                "text": "建议结合完整项目上下文复核。",
                "confidence": True,
                "uncertainty": "尚未完成医学经理确认。",
                "user_action": "请确认或修订。",
                "evidence_ids": ["evidence-001"],
            }
        )

    with pytest.raises(ValidationError):
        monitoring_ai_service_module._FieldMappingItem.model_validate(
            {
                "domain": "LB",
                "source_field": "LBORRES",
                "recommended_role": "lab_result_candidate",
                "field_kind": "source_collected",
                "confidence": True,
                "uncertainty": "仍需核对单位和参考范围字段。",
                "user_action": "请医学经理确认字段角色。",
                "related_fields": [],
                "evidence_ids": [],
            }
        )


@pytest.mark.parametrize(
    "profile_sha256",
    [
        f" {PROFILE_HASH}",
        f"{PROFILE_HASH} ",
        PROFILE_HASH.upper(),
        PROFILE_HASH[:-1],
        "g" * 64,
        123,
    ],
)
def test_service_profile_binding_rejects_noncanonical_digest_shapes(
    profile_sha256: Any,
) -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        monitoring_ai_service_module.monitoring_field_profile_source_binding(
            profile_sha256,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_content_sha256", f" {SOURCE_HASH}"),
        ("source_content_sha256", SOURCE_HASH.upper()),
        ("input_sha256", f"{INPUT_HASH} "),
    ],
)
def test_service_field_profile_rejects_noncanonical_persisted_digests(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    profile = _field_profile(1)
    if field == "source_content_sha256":
        profile["source_bindings"][0][field] = value
    else:
        profile[field] = value

    service = _service(tmp_path, FakeProvider([_valid_output]))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        service.submit_listing_field_mapping(
            project_id="project-alpha",
            input_revision=_revision(),
            field_profile=profile,
        )


def test_provider_payload_does_not_normalize_tampered_profile_digest(
    tmp_path: Path,
) -> None:
    profile = _field_profile(1)
    profile["fields"][0]["field"] = "DOMAIN"
    service = _service(tmp_path, FakeProvider([_valid_output]))
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )
    persisted_payload = service.repository.input_payload(
        job.project_id,
        job.job_id,
    )
    persisted_payload["field_profile"]["profile_sha256"] = (
        f" {PROFILE_HASH}"
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        MonitoringAiService._provider_input_payload(job, persisted_payload)


def test_my008_scale_profile_chunks_cover_all_fields_stably(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    full_profile = _my008_scale_field_profile()

    jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=full_profile,
        chunk_size=12,
    )
    repeated_jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=full_profile,
        chunk_size=12,
    )

    assert len(jobs) == 128
    assert [job.job_id for job in repeated_jobs] == [job.job_id for job in jobs]
    expected_pairs = {
        (field["domain"], field["field"]) for field in full_profile["fields"]
    }
    submitted_pairs: List[tuple[str, str]] = []
    ordered_chunk_keys: List[tuple[str, int]] = []
    payload_by_job_id: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        payload = service.repository.input_payload(
            job.project_id,
            job.job_id,
        )
        payload_by_job_id[job.job_id] = payload
        chunk = payload["field_profile"]
        domain = chunk["domain"]
        chunk_index = chunk["chunk_index"]
        ordered_chunk_keys.append((domain, chunk_index))
        assert chunk["scope"] == "complete_profile_chunk"
        assert chunk["full_profile_sha256"] == PROFILE_HASH
        assert chunk["full_input_sha256"] == INPUT_HASH
        assert chunk["full_field_count"] == 1454
        assert len(chunk["domain_field_names"]) == chunk["domain_field_count"]
        assert chunk["domain_field_names"] == sorted(
            chunk["domain_field_names"],
            key=lambda value: (value.casefold(), value),
        )
        assert chunk["row_count"] == 8699
        assert chunk["source_bindings"] == full_profile["source_bindings"]
        assert 1 <= len(chunk["fields"]) <= 12
        assert all(field["domain"] == domain for field in chunk["fields"])
        field_names = [field["field"] for field in chunk["fields"]]
        assert field_names == sorted(field_names)
        assert set(field_names).issubset(set(chunk["domain_field_names"]))
        assert job.business_key == (
            "listing-field-mapping:"
            f"MY008-20250417:{domain}:"
            f"{chunk_index:04d}-of-{chunk['chunk_total']:04d}"
        )
        submitted_pairs.extend(
            (field["domain"], field["field"]) for field in chunk["fields"]
        )

    assert ordered_chunk_keys == sorted(ordered_chunk_keys)
    assert len(submitted_pairs) == 1454
    assert len(set(submitted_pairs)) == 1454
    assert set(submitted_pairs) == expected_pairs

    completed_job_ids = set()
    while True:
        result = service.run_next("worker-scale")
        if not result.processed:
            break
        assert result.job is not None
        assert result.job.status == MonitoringAiJobStatus.COMPLETED
        completed_job_ids.add(result.job.job_id)
        candidates = service.repository.candidates(
            result.job.project_id,
            result.job.job_id,
        )
        assert len(candidates) == 1
        mappings = candidates[0].structured_payload["field_mappings"]
        chunk_fields = payload_by_job_id[result.job.job_id]["field_profile"]["fields"]
        assert {
            (mapping["domain"], mapping["source_field"]) for mapping in mappings
        } == {(field["domain"], field["field"]) for field in chunk_fields}
        assert len(mappings) == len(chunk_fields)
    assert completed_job_ids == {job.job_id for job in jobs}


def test_listing_field_mapping_chunks_reject_boolean_chunk_size(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeProvider([_valid_output]))

    with pytest.raises(ValueError, match="chunk_size must be an integer"):
        service.submit_listing_field_mapping_chunks(
            project_id="project-alpha",
            input_revision=_revision(),
            field_profile=_field_profile(),
            chunk_size=True,
        )


def test_listing_field_mapping_rejects_incomplete_chunk_contract(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeProvider([_valid_output]))
    invalid_chunk = _field_profile()
    invalid_chunk["scope"] = "complete_profile_chunk"
    invalid_chunk["domain"] = "LB"

    with pytest.raises(ValueError, match="chunk is incomplete"):
        service.submit_listing_field_mapping(
            project_id="project-alpha",
            input_revision=_revision(),
            field_profile=invalid_chunk,
        )


def test_listing_field_profile_rejects_boolean_numeric_fields(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeProvider([_valid_output]))
    row_count_profile = _field_profile()
    row_count_profile["row_count"] = True

    relationship_profile = _field_profile()
    relationship_profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "LB_FIELD_00",
            "right_field": "LB_FIELD_01",
            "relationship_type": "term_code_pair",
            "total_rows": True,
            "jointly_non_empty_count": 0,
            "left_only_count": 0,
            "right_only_count": 0,
            "unique_pair_count": 0,
            "left_values_with_multiple_right": 0,
            "right_values_with_multiple_left": 0,
        }
    ]

    chunk_profile = _field_profile()
    chunk_profile.update(
        {
            "scope": "complete_profile_chunk",
            "full_profile_sha256": PROFILE_HASH,
            "full_input_sha256": INPUT_HASH,
            "full_field_count": True,
            "domain": "LB",
            "domain_field_count": 8,
            "domain_field_names": [
                field["field"] for field in chunk_profile["fields"]
            ],
            "chunk_index": 1,
            "chunk_total": 1,
            "chunk_size_limit": 12,
        }
    )

    for profile, message in (
        (row_count_profile, "row_count must be positive"),
        (relationship_profile, "relationship counts must be non-negative"),
        (chunk_profile, "chunk counts must be positive"),
    ):
        with pytest.raises(ValueError, match=message):
            service.submit_listing_field_mapping(
                project_id="project-alpha",
                input_revision=_revision(),
                field_profile=profile,
            )


def test_listing_profile_requires_exact_paired_source_bindings(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    mismatched = _field_profile()
    mismatched["source_bindings"] = [
        {
            "source_entry_id": "source-listing",
            "source_content_sha256": "d" * 64,
        }
    ]

    with pytest.raises(ValueError, match="exact input revision"):
        service.submit_listing_field_mapping(
            project_id="project-alpha",
            input_revision=_revision(),
            field_profile=mismatched,
        )


def test_one_controlled_json_repair_can_complete(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            lambda _envelope: {"invalid": "shape"},
            _valid_output,
        ]
    )
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    assert provider.envelopes[1].payload["repair_contract"] == {
        "attempt": 1,
        "maximum_repairs": 1,
        "instruction": "按原始任务和output_schema重建完整JSON对象。",
    }
    repair_payload = provider.envelopes[1].payload
    assert set(repair_payload) == {
        "schema_version",
        "output_schema",
        "validation_errors",
        "invalid_output",
        "original_task",
        "authorized_source_pairs",
        "repair_contract",
        "deterministic_field_constraints",
    }
    assert repair_payload["deterministic_field_constraints"] == {
        "must_not_emit_fields_outside_inference_subset": True,
        "required_output_pairs": [
            {"domain": item["domain"], "source_field": item["field"]}
            for item in _field_profile()["fields"]
        ],
        "must_be_unmapped": [],
        "instruction": (
            "只重建required_output_pairs列出的本次AI字段子集；每项恰好"
            "输出一次，不得输出任何其他字段。即使某字段看起来属于技术"
            "元数据，只要出现在required_output_pairs中也必须输出。"
            "全空的剩余业务字段必须保持unmapped。"
        ),
    }
    assert repair_payload["invalid_output"] == {"invalid": "shape"}
    assert "Field required" in repair_payload["validation_errors"]
    repair_input = repair_payload["original_task"]["input_payload"]
    assert repair_input["field_profile"]["fields"] == _field_profile()["fields"]
    assert repair_input["field_profile"]["inference_scope"] == (
        "remaining_semantic_fields"
    )
    assert repair_input["field_profile"]["original_chunk_field_count"] == 8
    assert repair_input["field_profile"]["deterministic_metadata_field_count"] == 0


def test_two_invalid_outputs_fail_without_third_call(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            lambda _envelope: {"invalid": 1},
            lambda _envelope: {"still_invalid": 2},
        ]
    )
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert len(provider.envelopes) == 2


def test_response_model_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    provider = FakeProvider([_valid_output], response_model="wrong-model")
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "response_model_identity"


def test_missing_response_model_identity_fails_closed(tmp_path: Path) -> None:
    provider = FakeProvider([_valid_output], response_model="")
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "response_model_identity"
    assert len(provider.envelopes) == 1


@pytest.mark.parametrize("transport", ["hermes_cli", "codex_cli", "agent"])
def test_non_product_transport_is_rejected_before_provider_factory(
    tmp_path: Path,
    transport: str,
) -> None:
    runtime = _runtime()
    rejected_runtime = MonitoringAiRuntimeBinding(
        profile_id=runtime.profile_id,
        provider=runtime.provider,
        model=runtime.model,
        env={
            **runtime.env,
            "WORKBENCH_AI_TRANSPORT": transport,
        },
        transport=transport,
    )
    factory_calls = {"count": 0}

    def forbidden_factory(_env: Dict[str, str]) -> FakeProvider:
        factory_calls["count"] += 1
        raise AssertionError(
            "CLI/Agent product harness must not be instantiated"
        )

    service = MonitoringAiService(
        MonitoringAiRepository(tmp_path / f"{transport}.sqlite3"),
        runtime_resolver=lambda: rejected_runtime,
        provider_factory=forbidden_factory,
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "ai_transport_rejected"
    assert factory_calls["count"] == 0


def test_non_runnable_openai_runtime_is_rejected_before_provider_factory(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    missing_credential = MonitoringAiRuntimeBinding(
        profile_id=runtime.profile_id,
        provider=runtime.provider,
        model=runtime.model,
        env={
            **runtime.env,
            "WORKBENCH_AI_API_KEY": "",
        },
    )
    factory_calls = {"count": 0}

    def forbidden_factory(_env: Dict[str, str]) -> FakeProvider:
        factory_calls["count"] += 1
        raise AssertionError("unrunnable runtime must not reach provider factory")

    service = MonitoringAiService(
        MonitoringAiRepository(tmp_path / "missing-key.sqlite3"),
        runtime_resolver=lambda: missing_credential,
        provider_factory=forbidden_factory,
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "ai_not_configured"
    assert factory_calls["count"] == 0


def test_provider_transport_is_verified_after_factory(tmp_path: Path) -> None:
    provider = FakeProvider([_valid_output])
    provider.transport_name = "hermes_cli"
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "ai_transport_rejected"
    assert provider.envelopes == []


def test_provider_expected_response_model_is_verified_before_call(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([_valid_output])
    provider.expected_response_model = "different-model"
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "response_model_identity"
    assert provider.envelopes == []


class _RuntimeProviderStore:
    def __init__(self, profile: SimpleNamespace) -> None:
        self._profile = profile

    def profile(self, profile_id: str) -> SimpleNamespace:
        assert profile_id == self._profile.profile_id
        return self._profile


class _RuntimeRoleStore:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        transport: str,
        api_key: str,
    ) -> None:
        self._binding = SimpleNamespace(
            enabled=True,
            profile_id="independent-ai-profile",
            model=model,
        )
        self.provider_store = _RuntimeProviderStore(
            SimpleNamespace(
                profile_id=self._binding.profile_id,
                enabled=True,
                provider=provider,
                model=model,
                transport=transport,
            )
        )
        self._env = {
            "WORKBENCH_AI_PROVIDER": provider,
            "WORKBENCH_AI_TRANSPORT": transport,
            "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
            "WORKBENCH_AI_API_KEY": api_key,
            "WORKBENCH_AI_MODEL": model,
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": model,
            "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
        }

    def binding(self, role_id: str) -> SimpleNamespace:
        assert role_id == "independent_ai"
        return self._binding

    def role_env(self, role_id: str) -> Dict[str, str]:
        assert role_id == "independent_ai"
        return dict(self._env)


def test_runtime_resolver_accepts_runnable_generic_openai_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RuntimeRoleStore(
        provider="buddy-compatible-provider",
        model="shared-product-model",
        transport="openai_compatible",
        api_key="test-key",
    )
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "runtime_ai_role_settings_store",
        lambda: store,
    )

    runtime = resolve_monitoring_ai_runtime()

    assert runtime.available is True
    assert runtime.profile_id == "independent-ai-profile"
    assert runtime.provider == "buddy-compatible-provider"
    assert runtime.model == "shared-product-model"
    assert runtime.transport == "openai_compatible"


def test_runtime_resolver_rejects_string_ai_status_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RuntimeRoleStore(
        provider="generic-provider",
        model="generic-model",
        transport="openai_compatible",
        api_key="test-key",
    )
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "runtime_ai_role_settings_store",
        lambda: store,
    )
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "ai_gateway_status_from_env",
        lambda _env: {
            "configured": "false",
            "semantic_ai_tasks_enabled": "false",
            "transport": "openai_compatible",
            "provider": "generic-provider",
            "model": "generic-model",
            "route_validation_errors": [],
            "missing_env": [],
        },
    )

    runtime = resolve_monitoring_ai_runtime()

    assert runtime.available is False
    assert runtime.failure_code == "ai_not_configured"


def test_runtime_transport_rejects_string_ai_status_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "ai_gateway_status_from_env",
        lambda _env: {
            "configured": "true",
            "semantic_ai_tasks_enabled": "true",
        },
    )

    with pytest.raises(
        monitoring_ai_service_module.MonitoringAiRuntimeUnavailableError,
        match="not currently runnable",
    ):
        MonitoringAiService._validate_runtime_transport(_runtime())


@pytest.mark.parametrize("transport", ["hermes_cli", "unknown_transport"])
def test_runtime_resolver_rejects_non_openai_shared_profile(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    store = _RuntimeRoleStore(
        provider="generic-provider",
        model="generic-model",
        transport=transport,
        api_key="test-key",
    )
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "runtime_ai_role_settings_store",
        lambda: store,
    )

    runtime = resolve_monitoring_ai_runtime()

    assert runtime.available is False
    assert runtime.failure_code == "ai_transport_rejected"
    assert runtime.transport == transport


def test_runtime_resolver_rejects_shared_profile_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RuntimeRoleStore(
        provider="generic-provider",
        model="generic-model",
        transport="openai_compatible",
        api_key="",
    )
    monkeypatch.setattr(
        monitoring_ai_service_module,
        "runtime_ai_role_settings_store",
        lambda: store,
    )

    runtime = resolve_monitoring_ai_runtime()

    assert runtime.available is False
    assert runtime.failure_code == "ai_not_configured"
    assert "not currently runnable" in runtime.diagnostic


def test_stale_input_revision_never_calls_provider(tmp_path: Path) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(
        tmp_path,
        provider,
        current_revision_resolver=lambda _job: "f" * 64,
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.STALE_INPUT
    assert result.job.failure_code == "stale_input_revision"
    assert provider.envelopes == []


def test_stale_input_revision_does_not_normalize_resolver_digest(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(
        tmp_path,
        provider,
        current_revision_resolver=lambda job: f" {job.input_revision_sha256}",
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.STALE_INPUT
    assert result.job.failure_code == "stale_input_revision"
    assert provider.envelopes == []


def test_revision_change_during_provider_call_discards_output_and_candidates(
    tmp_path: Path,
) -> None:
    revision_state = {"current": _revision().revision_sha256}

    def change_revision() -> None:
        revision_state["current"] = "f" * 64

    provider = FakeProvider([_valid_output], before_return=change_revision)
    service = _service(
        tmp_path,
        provider,
        current_revision_resolver=lambda _job: revision_state["current"],
    )
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )
    revision_state["current"] = job.input_revision_sha256

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.STALE_INPUT
    assert result.job.failure_code == "stale_input_revision"
    assert "after_initial_provider_call" in result.job.failure_message
    assert service.repository.candidates(job.project_id, job.job_id) == ()


def test_revision_change_during_repair_discards_repaired_candidates(
    tmp_path: Path,
) -> None:
    revision_state = {"current": _revision().revision_sha256}

    def repaired_then_change(
        envelope: AiPromptEnvelope,
    ) -> Dict[str, Any]:
        output = _valid_output(envelope)
        revision_state["current"] = "f" * 64
        return output

    provider = FakeProvider(
        [
            lambda _envelope: {"invalid": "shape"},
            repaired_then_change,
        ]
    )
    service = _service(
        tmp_path,
        provider,
        current_revision_resolver=lambda _job: revision_state["current"],
    )
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )
    revision_state["current"] = job.input_revision_sha256

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.STALE_INPUT
    assert result.job.failure_code == "stale_input_revision"
    assert "after_repair_provider_call" in result.job.failure_message
    assert service.repository.candidates(job.project_id, job.job_id) == ()


def test_expired_lease_cannot_complete_and_replacement_worker_can(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    first_provider = FakeProvider(
        [_valid_output],
        before_return=lambda: clock.advance(seconds=11),
    )
    service = _service(
        tmp_path,
        first_provider,
        clock=clock,
        lease_seconds=10,
    )
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    lost = service.run_next("worker-a")

    assert lost.lease_lost is True
    assert lost.processed is False
    assert lost.job is not None
    assert lost.job.status == MonitoringAiJobStatus.RUNNING

    replacement_provider = FakeProvider([_valid_output])
    replacement = MonitoringAiService(
        service.repository,
        runtime_resolver=_runtime,
        provider_factory=lambda _env: replacement_provider,
    )
    completed = replacement.run_next("worker-b")
    assert completed.job is not None
    assert completed.job.job_id == job.job_id
    assert completed.job.attempt_count == 2
    assert completed.job.status == MonitoringAiJobStatus.COMPLETED


def test_unavailable_ai_is_diagnostic_and_does_not_raise(tmp_path: Path) -> None:
    provider = FakeProvider([_valid_output])
    service = _service(
        tmp_path,
        provider,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding.unavailable(
            "no API credential configured"
        ),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.processed is True
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "ai_not_configured"
    assert "credential" in result.job.failure_message
    assert provider.envelopes == []


def test_monitoring_ai_uses_independent_timeout_without_mutating_profile_env(
    tmp_path: Path,
) -> None:
    captured = {}
    runtime_env = {
        "WORKBENCH_AI_PROVIDER": "test-provider",
        "WORKBENCH_AI_TRANSPORT": "openai_compatible",
        "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
        "WORKBENCH_AI_API_KEY": "test-key",
        "WORKBENCH_AI_MODEL": "test-model",
        "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "test-model",
        "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
        "WORKBENCH_AI_TIMEOUT_SECONDS": "300",
    }
    runtime = MonitoringAiRuntimeBinding(
        profile_id="independent-ai-test",
        provider="test-provider",
        model="test-model",
        env=runtime_env,
    )
    provider = FakeProvider([_valid_output])
    service = MonitoringAiService(
        MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3"),
        runtime_resolver=lambda: runtime,
        provider_factory=lambda env: (
            captured.update(env) or provider
        ),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert captured["WORKBENCH_AI_TIMEOUT_SECONDS"] == "600.0"
    assert runtime_env["WORKBENCH_AI_TIMEOUT_SECONDS"] == "300"


def _attacked_field_output(
    envelope: AiPromptEnvelope,
    attack: str,
) -> Dict[str, Any]:
    output = _valid_output(envelope)
    candidate = output["candidates"][0]
    mappings = candidate["structured_payload"]["field_mappings"]
    if attack == "wrong_candidate_type":
        candidate["candidate_type"] = "field_mapping"
    elif attack == "missing_profile_field":
        mappings.pop()
    elif attack == "duplicate_profile_field":
        mappings[-1]["domain"] = mappings[0]["domain"]
        mappings[-1]["source_field"] = mappings[0]["source_field"]
    elif attack == "unknown_structured_evidence":
        mappings[0]["evidence_ids"] = ["not-in-candidate-evidence"]
    elif attack == "sdtm_as_role":
        mappings[0]["recommended_role"] = "SDTM.LBORRES"
    elif attack == "sdtm_dataset_assertion":
        mappings[0]["uncertainty"] = "该文件是SDTM数据集。"
    elif attack == "derived_without_lineage":
        mappings[0]["field_kind"] = "deterministic_derived"
    elif attack == "standards_reference_not_reference_only":
        mappings[0]["standards_reference"] = {
            "reference_name": "SDTM",
            "reference_concept": "LBORRES",
            "reference_only": False,
            "uncertainty": "仅为概念参照。",
        }
    elif attack == "multiple_mapping_candidates":
        output["candidates"].append(dict(candidate))
    else:
        raise AssertionError(attack)
    return output


def test_field_mapping_allows_sdtm_only_as_reference_concept(
    tmp_path: Path,
) -> None:
    def reference_only_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping["standards_reference"] = {
            "reference_name": "SDTM",
            "reference_concept": "SDTM数据集变量 LBORRES",
            "reference_only": True,
            "uncertainty": "仅作为标准概念参照，不代表来源字段已符合该标准。",
        }
        return output

    provider = FakeProvider([reference_only_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
        business_key="reference-only-sdtm-concept",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    mapping = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0].structured_payload["field_mappings"][0]
    assert mapping["standards_reference"]["reference_only"] is True


def test_field_mapping_allows_non_assertive_sdtm_reference_wording(
    tmp_path: Path,
) -> None:
    def reference_wording_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping["uncertainty"] = (
            "字段语义仍需结合项目数据字典确认，可参考SDTM数据集变量定义。"
        )
        return output

    provider = FakeProvider([reference_wording_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
        business_key="non-assertive-sdtm-reference",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "wording",
    (
        "不能据此认为该字段符合SDTM，仍需项目数据字典确认。",
        "该字段是否符合SDTM尚需人工确认。",
        "该映射不代表该文件为SDTM，仅作标准参照。",
        "The reference does not mean the listing is SDTM compliant.",
    ),
)
def test_field_mapping_allows_qualified_sdtm_wording(
    tmp_path: Path,
    wording: str,
) -> None:
    def qualified_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping["uncertainty"] = wording
        return output

    provider = FakeProvider([qualified_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
        business_key=f"qualified-sdtm-{abs(hash(wording))}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "wording",
    (
        "该字段符合SDTM。",
        "该文件为SDTM数据集。",
        "This listing is SDTM compliant.",
    ),
)
def test_field_mapping_rejects_definitive_sdtm_wording(
    tmp_path: Path,
    wording: str,
) -> None:
    def definitive_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping["uncertainty"] = wording
        return output

    provider = FakeProvider([definitive_output, definitive_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
        business_key=f"definitive-sdtm-{abs(hash(wording))}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_candidate_type",
        "missing_profile_field",
        "duplicate_profile_field",
        "sdtm_as_role",
        "sdtm_dataset_assertion",
        "derived_without_lineage",
        "standards_reference_not_reference_only",
        "multiple_mapping_candidates",
    ],
)
def test_field_mapping_schema_attacks_fail_after_single_repair(
    tmp_path: Path,
    attack: str,
) -> None:
    provider = FakeProvider(
        [
            lambda envelope: _attacked_field_output(envelope, attack),
            lambda envelope: _attacked_field_output(envelope, attack),
        ]
    )
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert len(provider.envelopes) == 2


@pytest.mark.parametrize("field_name", ("__STUDYOID", "DOMAIN"))
def test_field_mapping_generates_explicit_metadata_without_calling_ai(
    tmp_path: Path,
    field_name: str,
) -> None:
    profile = _field_profile(1)
    profile["fields"][0]["field"] = field_name
    provider = FakeProvider([_valid_output, _valid_output])

    def forbidden_runtime() -> MonitoringAiRuntimeBinding:
        raise AssertionError("pure deterministic mapping must not resolve an AI runtime")

    service = _service(
        tmp_path,
        provider,
        runtime_resolver=forbidden_runtime,
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key=f"metadata-boundary-{field_name}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert result.job.provider == DETERMINISTIC_METADATA_PROVIDER
    assert result.job.response_model == DETERMINISTIC_METADATA_MODEL
    assert provider.envelopes == []
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    mapping = candidate.structured_payload["field_mappings"][0]
    origin = candidate.structured_payload["mapping_provenance"][
        "field_origins"
    ][0]
    assert mapping["source_field"] == field_name
    assert mapping["field_kind"] == "source_metadata"
    assert origin["origin"] == "deterministic_rule"
    assert origin["rule_version"] == DETERMINISTIC_METADATA_MAPPING_VERSION
    assert candidate.evidence[0].raw_fields["ai_inference_used"] is False
    attempt = service.repository.attempts(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert attempt["outcome"] == "success_deterministic"
    assert attempt["request"]["provider_called"] is False
    assert attempt["request"]["rule_version"] == (
        DETERMINISTIC_METADATA_MAPPING_VERSION
    )


def test_field_mapping_rejects_all_empty_field_with_clinical_role(
    tmp_path: Path,
) -> None:
    profile = _field_profile(1)
    profile["fields"][0].update(
        {
            "field": "EXADJ",
            "non_empty_count": 0,
            "null_rate": 1.0,
            "unique_value_count": 0,
            "representative_values": [],
        }
    )
    provider = FakeProvider([_valid_output, _valid_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="all-empty-boundary",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_field_mapping_accepts_metadata_and_all_empty_unmapped(
    tmp_path: Path,
) -> None:
    profile = _field_profile(2)
    profile["fields"][0]["field"] = "DOMAIN"
    profile["fields"][1].update(
        {
            "field": "EXADJ",
            "non_empty_count": 0,
            "null_rate": 1.0,
            "unique_value_count": 0,
            "representative_values": [],
        }
    )

    def compliant_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        mappings[0].update(
            {
                "recommended_role": "unmapped_pending_data_dictionary",
                "field_kind": "unmapped",
            }
        )
        return output

    provider = FakeProvider([compliant_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="metadata-empty-compliant",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert [
        item["field"]
        for item in provider.envelopes[0].payload["input_payload"][
            "field_profile"
        ]["fields"]
    ] == ["EXADJ"]
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    mappings = candidate.structured_payload["field_mappings"]
    assert [(item["source_field"], item["field_kind"]) for item in mappings] == [
        ("DOMAIN", "source_metadata"),
        ("EXADJ", "unmapped"),
    ]


def test_field_mapping_repair_receives_deterministic_field_constraints(
    tmp_path: Path,
) -> None:
    profile = _field_profile(3)
    profile["fields"][0]["field"] = "DOMAIN"
    profile["fields"][1]["field"] = "__STUDYOID"
    profile["fields"][2].update(
        {
            "field": "DDORRES",
            "non_empty_count": 0,
            "null_rate": 1.0,
            "unique_value_count": 0,
            "representative_values": [],
        }
    )

    def repaired_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        if "repair_contract" in envelope.payload:
            mappings[0]["field_kind"] = "unmapped"
        return output

    provider = FakeProvider([_valid_output, repaired_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="deterministic-repair-constraints",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    repair_payload = provider.envelopes[1].payload
    assert repair_payload["deterministic_field_constraints"][
        "must_not_emit_fields_outside_inference_subset"
    ] is True
    assert repair_payload["deterministic_field_constraints"][
        "must_be_unmapped"
    ] == [{"domain": "LB", "source_field": "DDORRES"}]


def test_read_only_form_context_includes_values_without_becoming_output(
    tmp_path: Path,
) -> None:
    profile = _field_profile(2)
    profile["fields"][0].update(
        {
            "domain": "TREATMENT",
            "field": "FORMNM",
            "top_values": [
                {
                    "value": "背景治疗记录",
                    "count": 147,
                    "observed_type": "string",
                }
            ],
            "representative_values": ["背景治疗记录"],
        }
    )
    profile["fields"][1].update(
        {
            "domain": "TREATMENT",
            "field": "DOSE_VALUE",
            "representative_values": [10],
            "top_values": [
                {"value": 10, "count": 100, "observed_type": "integer"}
            ],
        }
    )

    def maps_background_as_ip(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping.update(
            {
                "recommended_role": "ip.administration.dose",
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["DOSE_VALUE"],
                "dose_semantics": "actual_administered",
            }
        )
        return output

    provider = FakeProvider([maps_background_as_ip])
    service = _service(tmp_path, provider)
    jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        chunk_size=1,
    )
    assert len(jobs) == 2

    result = service.run_next("worker-a")
    if not provider.envelopes:
        result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    sent_profile = provider.envelopes[0].payload["input_payload"]["field_profile"]
    assert sent_profile["required_output_field_names"] == ["DOSE_VALUE"]
    context_field = sent_profile["read_only_domain_context"]["fields"][0]
    assert context_field["source_profile_identity"] == {
        "profile_sha256": PROFILE_HASH,
        "domain": "TREATMENT",
        "field": "FORMNM",
    }
    assert context_field["representative_values"] == ["背景治疗记录"]
    assert context_field["top_values"][0]["value"] == "背景治疗记录"
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    mapping = next(
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"] == "DOSE_VALUE"
    )
    assert mapping["recommended_role"] == "treatment.administration.neutral"
    assert mapping["object_identity"] == "background_therapy"
    assert "non_ip_treatment_neutralized" in mapping["quality_gate_actions"]


def test_read_only_context_rejects_non_boolean_redaction_flag() -> None:
    with pytest.raises(ValueError, match="values_redacted"):
        monitoring_ai_service_module._read_only_context_field(
            {
                "domain": "TREATMENT",
                "field": "FORMNM",
                "values_redacted": "false",
            },
            recommended_role="form_name",
            profile_sha256=PROFILE_HASH,
        )


def test_scale_total_context_closes_ambiguous_assessment_number_role(
    tmp_path: Path,
) -> None:
    profile = _field_profile(5)
    for field in profile["fields"]:
        field["domain"] = "RES_7"
    profile["fields"][0].update(
        {
            "field": "FORMNM",
            "representative_values": ["iTNSS/iTOSS评估-提前退出"],
            "top_values": [
                {
                    "value": "iTNSS/iTOSS评估-提前退出",
                    "count": 3,
                    "observed_type": "string",
                }
            ],
        }
    )
    for index in range(1, 4):
        profile["fields"][index].update(
            {
                "field": f"ITOSS{index}",
                "representative_values": [index],
            }
        )
    profile["fields"][4].update(
        {
            "field": "ITOSSNUM",
            "inferred_type": "integer",
            "representative_values": [7],
        }
    )

    def ambiguous_total(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        by_field = {item["source_field"]: item for item in mappings}
        by_field["ITOSSNUM"].update(
            {
                "recommended_role": "clinical_score_or_assessment_number",
                "confidence": 0.42,
                "related_fields": ["ITOSS1", "ITOSS2", "ITOSS3"],
            }
        )
        return output

    provider = FakeProvider([ambiguous_total])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="scale-total-closure",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    total = next(
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"] == "ITOSSNUM"
    )
    assert total["recommended_role"] == "scale.total_score"
    assert total["field_kind"] == "source_collected"
    assert total["related_fields"] == ["ITOSS1", "ITOSS2", "ITOSS3"]
    assert total["derivation_lineage"] is None
    assert "scale_source_total_closed" in total["quality_gate_actions"]
    assert "复算公式" in total["uncertainty"]


def test_explicit_cross_domain_binding_is_validated_and_materialized(
    tmp_path: Path,
) -> None:
    profile = _field_profile(2)
    profile["fields"][0].update(
        {"domain": "RANDOMIZATION", "field": "ARM"}
    )
    profile["fields"][1].update(
        {
            "domain": "IP_ADMIN",
            "field": "ACTUAL_DOSE",
            "representative_values": [20],
        }
    )
    profile["treatment_identity_bindings"] = [
        {
            "schema_version": "monitoring_treatment_identity_binding_v1",
            "binding_id": "rand-to-admin",
            "source_domain": "RANDOMIZATION",
            "source_field": "ARM",
            "target_domain": "IP_ADMIN",
            "relationship_type": "subject_level_randomized_assignment",
            "join_keys": ["subject_id"],
        }
    ]

    def bound_mapping(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        by_field = {item["source_field"]: item for item in mappings}
        by_field["ARM"].update(
            {
                "recommended_role": (
                    "treatment.identity.randomized_assignment"
                ),
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["ARM"],
            }
        )
        by_field["ACTUAL_DOSE"].update(
            {
                "recommended_role": "ip.administration.dose",
                "object_identity": "investigational_product",
                "object_identity_binding_id": "rand-to-admin",
                "dose_semantics": "actual_administered",
            }
        )
        return output

    provider = FakeProvider([bound_mapping])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="validated-cross-domain-binding",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    dose = next(
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"] == "ACTUAL_DOSE"
    )
    assert dose["recommended_role"] == "ip.administration.dose"
    assert dose["validated_treatment_identity_binding"]["binding_id"] == (
        "rand-to-admin"
    )


def test_dose_field_cannot_self_attest_investigational_product_identity(
    tmp_path: Path,
) -> None:
    profile = _field_profile(1)
    profile["fields"][0].update(
        {
            "domain": "EX",
            "field": "DOSE_VALUE",
            "representative_values": [10],
        }
    )

    def self_attested_ip(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ][0]
        mapping.update(
            {
                "recommended_role": "ip.administration.dose",
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["DOSE_VALUE"],
                "dose_semantics": "actual_administered",
            }
        )
        return output

    provider = FakeProvider([self_attested_ip])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="self-attested-ip-identity",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    mapping = candidate.structured_payload["field_mappings"][0]
    assert mapping["recommended_role"] == "treatment.administration.neutral"
    assert mapping["object_identity"] == "unresolved"
    assert "treatment_identity_unresolved" in mapping["quality_gate_actions"]


def test_indistinguishable_dose_fields_are_not_silently_selected(
    tmp_path: Path,
) -> None:
    profile = _field_profile(3)
    for field in profile["fields"]:
        field["domain"] = "IP_ADMIN"
    profile["fields"][0].update(
        {"field": "PRODUCT", "representative_values": ["试验药物A"]}
    )
    for index, field_name in enumerate(("DOSE_A", "DOSE_B"), start=1):
        profile["fields"][index].update(
            {
                "field": field_name,
                "representative_values": [10, 20],
                "top_values": [
                    {"value": 10, "count": 70, "observed_type": "integer"},
                    {"value": 20, "count": 70, "observed_type": "integer"},
                ],
            }
        )

    def ambiguous_doses(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        by_field = {item["source_field"]: item for item in mappings}
        by_field["PRODUCT"].update(
            {
                "recommended_role": (
                    "treatment.identity.investigational_product"
                ),
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["PRODUCT"],
            }
        )
        by_field["DOSE_A"].update(
            {
                "recommended_role": "ip.dose.planned",
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["PRODUCT"],
                "dose_semantics": "planned",
            }
        )
        by_field["DOSE_B"].update(
            {
                "recommended_role": "ip.administration.dose",
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["PRODUCT"],
                "dose_semantics": "actual_administered",
            }
        )
        return output

    provider = FakeProvider([ambiguous_doses])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="indistinguishable-dose-profile",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    doses = [
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"] in {"DOSE_A", "DOSE_B"}
    ]
    assert {item["dose_semantics"] for item in doses} == {"unresolved"}
    assert {
        item["recommended_role"] for item in doses
    } == {"ip.dose.unresolved"}
    assert all(
        "dose_semantics_unresolved" in item["quality_gate_actions"]
        for item in doses
    )


@pytest.mark.parametrize(
    ("marker", "expected_identity"),
    [
        ("既往用药", "background_therapy"),
        ("Prior Medication", "background_therapy"),
        ("既往治疗", "background_therapy"),
        ("prior therapy", "background_therapy"),
        ("非研究用药", "concomitant_non_ip"),
        ("非试验用药", "concomitant_non_ip"),
        ("non-study medication", "concomitant_non_ip"),
        ("non-study treatment", "concomitant_non_ip"),
        ("合并治疗", "concomitant_non_ip"),
        ("rescue medication", "rescue_therapy"),
    ],
)
def test_prior_and_non_study_context_neutralizes_provider_ip_claim(
    tmp_path: Path,
    marker: str,
    expected_identity: str,
) -> None:
    """Source-data prior/non-study treatment vocabulary neutralizes a
    provider IP claim even when role, object identity and cited evidence
    are mutually consistent (circular self-attestation)."""

    profile = _field_profile(2)
    profile["fields"][0].update(
        {
            "domain": "PM",
            "field": "MEDNAME",
            "representative_values": [f"{marker}A"],
        }
    )
    profile["fields"][1].update(
        {"domain": "PM", "field": "DOSE", "representative_values": [10]}
    )

    def maps_pm_as_ip(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"][
            "field_mappings"
        ]
        by_field = {item["source_field"]: item for item in mappings}
        by_field["MEDNAME"].update(
            {
                "recommended_role": (
                    "treatment.identity.investigational_product"
                ),
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["MEDNAME"],
            }
        )
        by_field["DOSE"].update(
            {
                "recommended_role": "ip.administration.dose",
                "object_identity": "investigational_product",
                "object_identity_evidence_fields": ["MEDNAME"],
                "dose_semantics": "actual_administered",
            }
        )
        return output

    provider = FakeProvider([maps_pm_as_ip])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key=f"pm-neutralize-{marker}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    dose = next(
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"] == "DOSE"
    )
    assert dose["object_identity"] == expected_identity
    assert dose["recommended_role"] == "treatment.administration.neutral"
    assert dose["dose_semantics"] == "unresolved"
    assert "non_ip_treatment_neutralized" in dose["quality_gate_actions"]


def test_my009_dd_mixed_chunk_excludes_formoid_and_domain_from_ai(
    tmp_path: Path,
) -> None:
    profile = _field_profile(3)
    profile["fields"][0].update(
        {
            "domain": "DD",
            "field": "__FORMOID",
            "non_empty_count": 0,
            "null_rate": 1.0,
            "unique_value_count": 0,
            "representative_values": [],
        }
    )
    profile["fields"][1].update({"domain": "DD", "field": "DOMAIN"})
    profile["fields"][2].update({"domain": "DD", "field": "DDTERM"})
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="my009-dd-mixed-deterministic-metadata",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    sent_profile = provider.envelopes[0].payload["input_payload"]["field_profile"]
    assert [
        (item["domain"], item["field"]) for item in sent_profile["fields"]
    ] == [("DD", "DDTERM")]
    assert "system_excluded_deterministic_fields" not in (
        provider.envelopes[0].payload["input_payload"]
    )

    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    mappings = candidate.structured_payload["field_mappings"]
    assert [
        (item["domain"], item["source_field"], item["field_kind"])
        for item in mappings
    ] == [
        ("DD", "__FORMOID", "source_metadata"),
        ("DD", "DOMAIN", "source_metadata"),
        ("DD", "DDTERM", "source_collected"),
    ]
    origins = candidate.structured_payload["mapping_provenance"]["field_origins"]
    assert [item["origin"] for item in origins] == [
        "deterministic_rule",
        "deterministic_rule",
        "independent_ai",
    ]
    evidence_by_field = {
        item.raw_fields["field"]: item.raw_fields for item in candidate.evidence
    }
    assert evidence_by_field["__FORMOID"]["ai_inference_used"] is False
    assert evidence_by_field["__FORMOID"]["deterministic_rule_id"] == (
        "exact_odm_form_oid"
    )
    assert evidence_by_field["DOMAIN"]["ai_inference_used"] is False
    assert evidence_by_field["DDTERM"]["ai_inference_used"] is True


def test_mixed_deterministic_and_ai_fields_assemble_into_one_auditable_draft(
    tmp_path: Path,
) -> None:
    profile = _field_profile(3)
    profile["batch_id"] = "MY009-DD"
    profile["expected_domains"] = ["DD"]
    profile["fields"][0].update({"domain": "DD", "field": "__FORMOID"})
    profile["fields"][1].update({"domain": "DD", "field": "DOMAIN"})
    profile["fields"][2].update({"domain": "DD", "field": "DDTERM"})
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)

    jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        chunk_size=12,
    )
    assert len(jobs) == 1
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    sent_profile = provider.envelopes[0].payload["input_payload"]["field_profile"]
    assert [item["field"] for item in sent_profile["fields"]] == ["DDTERM"]
    assert sent_profile["domain_field_names"] == ["DDTERM"]
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    service.repository.decide_candidate(
        "project-alpha",
        candidate.candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical-manager",
        reason="确认进入映射草稿",
        current_input_revision_sha256=result.job.input_revision_sha256,
    )

    draft_repository = MonitoringMappingDraftRepository(
        tmp_path / "monitoring-ai.sqlite3"
    )
    draft = draft_repository.assemble(
        "project-alpha",
        "MY009-DD",
        PROFILE_HASH,
        prompt_version=result.job.prompt_version,
    )

    assert [(field.source_field, field.field_kind.value) for field in draft.fields] == [
        ("DDTERM", "source_collected"),
        ("DOMAIN", "source_metadata"),
        ("__FORMOID", "source_metadata"),
    ]
    assert {
        (source.domain, source.source_field, source.candidate_id)
        for source in draft.field_sources
    } == {
        ("DD", "DOMAIN", candidate.candidate_id),
        ("DD", "DDTERM", candidate.candidate_id),
        ("DD", "__FORMOID", candidate.candidate_id),
    }


def test_mixed_chunk_rejects_ai_return_of_system_deterministic_field(
    tmp_path: Path,
) -> None:
    profile = _field_profile(2)
    profile["fields"][0].update({"domain": "DD", "field": "DOMAIN"})
    profile["fields"][1].update({"domain": "DD", "field": "DDTERM"})

    def returns_excluded_field(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = dict(
            output["candidates"][0]["structured_payload"]["field_mappings"][0]
        )
        mapping.update(
            {
                "source_field": "DOMAIN",
                "recommended_role": "source_domain_identifier",
                "field_kind": "source_metadata",
            }
        )
        output["candidates"][0]["structured_payload"]["field_mappings"].append(
            mapping
        )
        return output

    provider = FakeProvider([returns_excluded_field, returns_excluded_field])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="mixed-reject-system-field",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "system-owned deterministic metadata fields" in result.job.failure_message
    assert len(provider.envelopes) == 2


def test_mixed_chunk_rejects_omitted_remaining_ai_field(
    tmp_path: Path,
) -> None:
    profile = _field_profile(2)
    profile["fields"][0].update({"domain": "DD", "field": "__FORMOID"})
    profile["fields"][1].update({"domain": "DD", "field": "DDTERM"})

    def omits_remaining_field(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["field_mappings"] = []
        return output

    provider = FakeProvider([omits_remaining_field, omits_remaining_field])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
        business_key="mixed-reject-omitted-field",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "cover every input profile field exactly once" in (
        result.job.failure_message
    )
    assert len(provider.envelopes) == 2


@pytest.mark.parametrize(
    ("field_name", "expected_role"),
    (
        ("__CUSTOMOID", "edc_object_identifier"),
        ("__CUSTOMREPEATKEY", "edc_repeat_key"),
        ("STUDYID", "study_identifier"),
        ("SITEID", "site_identifier"),
        ("SITENM", "site_name"),
        ("SUBJID", "subject_identifier"),
        ("SUBJINI", "subject_initials"),
        ("USUBJID", "subject_identifier"),
        ("VISIT", "visit_name"),
        ("VISITNUM", "visit_sequence_number"),
        ("VISTOID", "visit_identifier"),
        ("VISTREP", "visit_repeat_key"),
        ("FORMOID", "form_identifier"),
        ("FORMREP", "form_repeat_key"),
        ("RECREP", "record_repeat_key"),
        ("CRFVER", "crf_version"),
        ("FORMNM", "form_name"),
        ("GROUPID", "record_group_identifier"),
        ("Block顺序号", "record_block_sequence"),
        ("FORMNM__2", "form_name_duplicate"),
        ("ISDEL", "record_deletion_flag"),
        ("PAGEFSDT", "page_first_saved_datetime"),
        ("PAGELMBY", "page_last_modified_by"),
        ("PAGELMDT", "page_last_modified_datetime"),
        ("PSTUDYID", "study_identifier"),
        ("PSTUDYNM", "study_name"),
    ),
)
def test_deterministic_metadata_whitelist_and_naming_rules(
    field_name: str,
    expected_role: str,
) -> None:
    decision = deterministic_metadata_decision("DD", field_name)

    assert decision is not None
    assert decision.recommended_role == expected_role


@pytest.mark.parametrize(
    "field_name",
    (
        "PAGE",
        "FORM",
        "LINE",
        "AEOID",
        "REPEATKEY",
        "DOMAIN_LABEL",
        "__CLINICALTERM",
    ),
)
def test_business_or_ambiguous_fields_do_not_match_metadata_rules(
    field_name: str,
) -> None:
    assert deterministic_metadata_decision("DD", field_name) is None


def test_cm_cannot_be_mapped_to_ip_dose_adjustment_role(
    tmp_path: Path,
) -> None:
    profile = _field_profile()
    profile["fields"][0]["domain"] = "CM"

    def invalid_cm_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["field_mappings"][0][
            "recommended_role"
        ] = "ip_dose_adjustment"
        return output

    provider = FakeProvider([invalid_cm_output, invalid_cm_output])
    service = _service(tmp_path, provider)
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_field_mapping_system_materializes_profile_evidence(
    tmp_path: Path,
) -> None:
    def compact_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate.pop("claims")
        candidate.pop("evidence")
        for mapping in candidate["structured_payload"]["field_mappings"]:
            mapping.pop("evidence_ids")
        return output

    service = _service(tmp_path, FakeProvider([compact_output]))
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(job.project_id, job.job_id)[0]
    assert len(candidate.evidence) == len(_field_profile()["fields"])
    assert all(
        evidence.locator.startswith("field-profile://")
        for evidence in candidate.evidence
    )
    assert {
        (evidence.raw_fields["domain"], evidence.raw_fields["field"])
        for evidence in candidate.evidence
    } == {
        (field["domain"], field["field"])
        for field in _field_profile()["fields"]
    }
    assert all(
        mapping["evidence_ids"]
        for mapping in candidate.structured_payload["field_mappings"]
    )


@pytest.mark.parametrize(
    "relationship_type",
    [
        "term_code_pair",
        "site_identity_pair",
        "visit_identity_pair",
        "value_unit_pair",
        "performed_reason_pair",
    ],
)
def test_field_mapping_accepts_the_closed_profiler_relationship_contract(
    tmp_path: Path,
    relationship_type: str,
) -> None:
    profile = _field_profile(field_count=2)
    profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "LB_FIELD_00",
            "right_field": "LB_FIELD_01",
            "relationship_type": relationship_type,
            "total_rows": 147,
            "jointly_non_empty_count": 140,
            "left_only_count": 0,
            "right_only_count": 0,
            "unique_pair_count": 25,
            "left_values_with_multiple_right": 0,
            "right_values_with_multiple_left": 0,
        }
    ]
    service = _service(tmp_path, FakeProvider([_valid_output]))

    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )

    assert job.status == MonitoringAiJobStatus.QUEUED


def test_field_mapping_rejects_relationship_type_outside_closed_contract(
    tmp_path: Path,
) -> None:
    profile = _field_profile(field_count=2)
    profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "LB_FIELD_00",
            "right_field": "LB_FIELD_01",
            "relationship_type": "free_text_guess",
            "total_rows": 147,
            "jointly_non_empty_count": 140,
            "left_only_count": 0,
            "right_only_count": 0,
            "unique_pair_count": 25,
            "left_values_with_multiple_right": 0,
            "right_values_with_multiple_left": 0,
        }
    ]
    service = _service(tmp_path, FakeProvider([_valid_output]))

    with pytest.raises(
        ValueError,
        match="listing field relationship is malformed",
    ):
        service.submit_listing_field_mapping(
            project_id="project-alpha",
            input_revision=_revision(),
            field_profile=profile,
        )


def test_standardized_coded_mapping_requires_same_row_pairing_and_lineage(
    tmp_path: Path,
) -> None:
    profile = _field_profile(field_count=3)
    profile["fields"][0]["field"] = "不良事件名称 PT"
    profile["fields"][1]["field"] = "不良事件名称 PT CODE"
    profile["fields"][2]["field"] = "MDRAVER"
    profile["fields"][2]["representative_values"] = ["26.0"]
    profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "不良事件名称 PT",
            "right_field": "不良事件名称 PT CODE",
            "relationship_type": "term_code_pair",
            "total_rows": 147,
            "jointly_non_empty_count": 140,
            "left_only_count": 0,
            "right_only_count": 0,
            "unique_pair_count": 25,
            "left_values_with_multiple_right": 0,
            "right_values_with_multiple_left": 0,
        }
    ]

    def coded_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"]["field_mappings"]
        coded = next(
            item for item in mappings if item["source_field"].endswith("CODE")
        )
        coded["field_kind"] = "standardized_coded"
        coded["recommended_role"] = "meddra_preferred_term_code"
        coded["derivation_lineage"] = {
            "source_fields": ["不良事件名称 PT"],
            "coding_system": "MedDRA",
            "dictionary_version_field": "MDRAVER",
        }
        coded["confidence"] = 0.9
        return output

    service = _service(tmp_path, FakeProvider([coded_output]))
    job = service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(job.project_id, job.job_id)[0]
    coded_mapping = next(
        item
        for item in candidate.structured_payload["field_mappings"]
        if item["source_field"].endswith("CODE")
    )
    evidence = next(
        item
        for item in candidate.evidence
        if item.evidence_id in coded_mapping["evidence_ids"]
    )
    assert evidence.source_entry_id.startswith("field-profile:")
    assert evidence.raw_fields["paired_relationships"] == profile["relationships"]


def test_imperfect_term_code_pairing_caps_mapping_confidence(
    tmp_path: Path,
) -> None:
    profile = _field_profile(field_count=3)
    profile["fields"][0]["field"] = "AETERM"
    profile["fields"][1]["field"] = "AEDECOD"
    profile["fields"][2]["field"] = "MDRAVER"
    profile["fields"][2]["representative_values"] = ["26.0"]
    profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "AETERM",
            "right_field": "AEDECOD",
            "relationship_type": "term_code_pair",
            "total_rows": 147,
            "jointly_non_empty_count": 138,
            "left_only_count": 2,
            "right_only_count": 0,
            "unique_pair_count": 25,
            "left_values_with_multiple_right": 1,
            "right_values_with_multiple_left": 0,
        }
    ]

    def overconfident_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mappings = output["candidates"][0]["structured_payload"]["field_mappings"]
        coded = next(item for item in mappings if item["source_field"] == "AEDECOD")
        coded.update(
            {
                "field_kind": "standardized_coded",
                "recommended_role": "meddra_preferred_term",
                "confidence": 0.95,
                "derivation_lineage": {
                    "source_fields": ["AETERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            }
        )
        return output

    service = _service(
        tmp_path,
        FakeProvider([overconfident_output, overconfident_output]),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


@pytest.mark.parametrize(
    ("coding_system", "dictionary_version_field", "source_fields"),
    [
        ("ATC", "ATC1TEXT", ["ATC1TEXT"]),
        ("unspecified drug coding system", "DRUGVER", ["DRUGNAME"]),
        ("MedDRA", "MDRAVER", ["PTCODE"]),
    ],
)
def test_standardized_coded_mapping_rejects_false_lineage(
    tmp_path: Path,
    coding_system: str,
    dictionary_version_field: str,
    source_fields: list[str],
) -> None:
    profile = _field_profile(field_count=3)
    profile["fields"][0]["field"] = "PTTERM"
    profile["fields"][1]["field"] = "PTCODE"
    profile["fields"][2]["field"] = (
        "ATC1TEXT" if dictionary_version_field == "ATC1TEXT" else "MDRAVER"
    )
    profile["relationships"] = [
        {
            "domain": "LB",
            "left_field": "PTTERM",
            "right_field": "PTCODE",
            "relationship_type": "term_code_pair",
            "total_rows": 147,
            "jointly_non_empty_count": 140,
            "left_only_count": 0,
            "right_only_count": 0,
            "unique_pair_count": 25,
            "left_values_with_multiple_right": 0,
            "right_values_with_multiple_left": 0,
        }
    ]

    def false_lineage_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = next(
            item
            for item in output["candidates"][0]["structured_payload"][
                "field_mappings"
            ]
            if item["source_field"] == "PTCODE"
        )
        mapping.update(
            {
                "field_kind": "standardized_coded",
                "recommended_role": "coded_preferred_term",
                "confidence": 0.8,
                "derivation_lineage": {
                    "source_fields": source_fields,
                    "coding_system": coding_system,
                    "dictionary_version_field": dictionary_version_field,
                },
            }
        )
        return output

    service = _service(
        tmp_path,
        FakeProvider([false_lineage_output, false_lineage_output]),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=profile,
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_ai_field_profile_cannot_assert_deterministic_derivation(
    tmp_path: Path,
) -> None:
    def derived_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        mapping = output["candidates"][0]["structured_payload"]["field_mappings"][0]
        mapping.update(
            {
                "field_kind": "deterministic_derived",
                "recommended_role": "derived_dose",
                "derivation_lineage": {
                    "source_fields": ["LB_FIELD_01"],
                    "formula": "LB_FIELD_01 * 2",
                },
            }
        )
        return output

    service = _service(
        tmp_path,
        FakeProvider([derived_output, derived_output]),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_field_mapping_rejects_english_only_user_facing_guidance(
    tmp_path: Path,
) -> None:
    def english_only(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate["title"] = "Field mapping"
        for mapping in candidate["structured_payload"]["field_mappings"]:
            mapping["uncertainty"] = "Needs data dictionary confirmation."
            mapping["user_action"] = "Confirm the field role."
        return output

    service = _service(
        tmp_path,
        FakeProvider([english_only, english_only]),
    )
    service.submit_listing_field_mapping(
        project_id="project-alpha",
        input_revision=_revision(),
        field_profile=_field_profile(),
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


@pytest.mark.parametrize(
    ("task_type", "expected_gateway_type"),
    [
        item
        for item in AI_TASK_TYPE_BY_MONITORING_TASK.items()
        if item[0]
        != MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION
    ],
)
def test_general_task_prompt_contracts_map_to_existing_gateway_types(
    tmp_path: Path,
    task_type: MonitoringAiTaskType,
    expected_gateway_type: AiTaskType,
) -> None:
    candidate_count = (
        2
        if task_type
        in (
            MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
            MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
        )
        else 1
    )
    provider = FakeProvider(
        [
            lambda envelope: _valid_output(
                envelope,
                candidate_count=candidate_count,
            )
        ]
    )
    service = _service(tmp_path, provider)
    if task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
        input_payload = {"field_profile": _field_profile()}
    else:
        input_payload = _nonmapping_input_payload(
            source_context={
                "question": "请提出可追溯候选。",
                "evidence_scope": "authorized sources only",
            },
        )
    effective_revision = (
        monitoring_revision_with_field_profile(_revision(), PROFILE_HASH)
        if task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING
        else _revision()
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=task_type,
        input_revision=effective_revision,
        input_payload=input_payload,
        business_key=f"task-{task_type.value}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert provider.envelopes[0].task_type == expected_gateway_type
    assert provider.envelopes[0].payload["task_contract"]


@pytest.mark.parametrize(
    "task_type",
    [
        MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        MonitoringAiTaskType.RISK_QUESTION_ANSWER,
        MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
    ],
)
def test_non_mapping_tasks_reject_empty_structured_payload(
    tmp_path: Path,
    task_type: MonitoringAiTaskType,
) -> None:
    candidate_count = (
        2 if task_type == MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES else 1
    )

    def invalid_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(
            envelope,
            candidate_count=candidate_count,
        )
        for candidate in output["candidates"]:
            candidate["structured_payload"] = {}
        return output

    provider = FakeProvider([invalid_output, invalid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=task_type,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            source_context={"case_id": "case-001"},
        ),
        business_key=f"invalid-{task_type.value}",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert len(provider.envelopes) == 2


def test_non_mapping_task_rejects_wrong_candidate_type(
    tmp_path: Path,
) -> None:
    def invalid_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["candidate_type"] = "generic_candidate"
        return output

    provider = FakeProvider([invalid_output, invalid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_context={"risk_id": "risk-001"},
        ),
        business_key="wrong-candidate-type",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_non_mapping_rejects_internal_ids_in_user_facing_text(
    tmp_path: Path,
) -> None:
    def invalid_output(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["title"] = (
            "风险实例 riskinst_private_001 证据摘要"
        )
        return output

    provider = FakeProvider([invalid_output, invalid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_instance_id="riskinst_private_001",
        ),
        business_key="internal-id-leak",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "internal IDs" in result.job.failure_message


def test_cross_table_risk_task_system_materializes_subject_reference(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [lambda envelope: _valid_output(envelope, candidate_count=2)]
    )
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_instance_id="riskinst_private_001",
        ),
        business_key="system-subject-reference",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["subject_id"] == "<current-subject>"
    assert candidate.structured_payload["domains"] == ["AE", "CM"]


def test_protocol_clause_candidate_keeps_only_referenced_evidence(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(purpose="结构化禁用药条款"),
        business_key="protocol-evidence-pruning",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert [item.evidence_id for item in candidate.evidence] == ["evidence-1"]


def test_protocol_clause_candidate_rejects_unknown_claim_evidence(
    tmp_path: Path,
) -> None:
    def unknown_claim_evidence(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["claims"][0]["evidence_ids"] = ["not-authorized"]
        return output

    service = _service(
        tmp_path,
        FakeProvider([unknown_claim_evidence, unknown_claim_evidence]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(purpose="结构化禁用药条款"),
        business_key="reject-unknown-claim-evidence",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "claim references unknown" in result.job.failure_message


def _protocol_v2_conflict_input_payload() -> Dict[str, Any]:
    payload = _nonmapping_input_payload()
    payload["context"] = {
        "workflow": "monitoring_protocol_preparation_v2",
        "evidence_packet_version": "monitoring_protocol_evidence_packet_v3",
        "topic_id": "study_treatment",
        "absence_assertion_authority": "none",
        "detected_source_conflicts": [
            {
                "conflict_id": "protocol_conflict_stop",
                "object_scope": "investigational_product",
                "action": "stop",
                "modalities": ["required", "optional"],
                "status": "requires_user_resolution",
                "evidence_ids": ["evidence-1", "evidence-2"],
            }
        ],
        "candidate_fact_types": [
            "study_treatment_regimen",
            "study_treatment_change",
            "study_treatment_adherence",
        ],
    }
    for index, item in enumerate(payload["evidence_packet"], start=1):
        item["raw_fields"]["protocol_context"] = {
            "packet_version": "monitoring_protocol_evidence_packet_v3",
            "primary_match": index <= 2,
            "roles": ["primary_match"] if index <= 2 else ["adjacent_paragraph"],
            "eligible_for_rule_fact": True,
            "structure": {"kind": "paragraph"},
        }
    payload["evidence_packet"][0]["quote"] = "受试者需停用研究药物。"
    payload["evidence_packet"][1]["quote"] = "受试者可停用研究药物。"
    return payload


def test_protocol_v2_rejects_silent_conflict_resolution(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        FakeProvider([_valid_output, _valid_output]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_protocol_v2_conflict_input_payload(),
        business_key="protocol-v2-silent-conflict",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "source conflicts" in result.job.failure_message


def test_protocol_v2_accepts_exact_conflict_with_user_resolution(
    tmp_path: Path,
) -> None:
    def conflict_preserved(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        candidate["structured_payload"]["source_conflicts"] = [
            {
                "conflict_id": "protocol_conflict_stop",
                "action": "stop",
                "modalities": ["required", "optional"],
                "status": "requires_user_resolution",
                "evidence_ids": ["evidence-1", "evidence-2"],
            }
        ]
        candidate["claims"][0].update(
            {
                "kind": "data_gap",
                "text": "原文对同一停药动作存在强制与可选措辞冲突。",
                "uncertainty": "冲突原文均有效，系统不得代替用户裁决。",
                "user_action": "请基于并列原文确认最终执行要求。",
                "evidence_ids": ["evidence-1", "evidence-2"],
            }
        )
        return output

    service = _service(tmp_path, FakeProvider([conflict_preserved]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_protocol_v2_conflict_input_payload(),
        business_key="protocol-v2-preserved-conflict",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["source_conflicts"][0][
        "status"
    ] == "requires_user_resolution"


def test_protocol_v2_rejects_protocol_absence_claim_from_bounded_packet(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_conflict_input_payload()
    payload["context"]["detected_source_conflicts"] = []

    def unsupported_absence(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["text"] = "研究方案未规定具体访视时间窗。"
        return output

    service = _service(
        tmp_path,
        FakeProvider([unsupported_absence, unsupported_absence]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-unsupported-absence",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "retrieval gap" in result.job.failure_message


@pytest.mark.parametrize(
    "negated_absence",
    [
        "当前证据包未检索到具体时限，不能断言方案未规定具体时限。",
        "该缺口不代表方案未规定；仅表示本次授权证据包未覆盖相应段落。",
        "受检索范围限制，不能据此推断方案未规定其他监查方式。",
    ],
)
def test_protocol_v2_allows_explicitly_negated_absence_claim(
    tmp_path: Path,
    negated_absence: str,
) -> None:
    payload = _protocol_v2_conflict_input_payload()
    payload["context"]["detected_source_conflicts"] = []

    def compliant_gap(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["claims"][0]["uncertainty"] = negated_absence
        return output

    service = _service(tmp_path, FakeProvider([compliant_gap]))
    job = service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-negated-absence",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert service.repository.candidates(job.project_id, job.job_id)


def test_protocol_v2_repair_binds_same_row_threshold_and_header(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ]
    )

    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-repair-table-bundle",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["evidence_ids"] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
    ]
    lineage = candidate.structured_payload["repair_lineage"]
    assert lineage["schema_version"] == (
        "monitoring_protocol_structural_repair_v2"
    )
    assert lineage["original_evidence_ids"] == ["evidence-1"]
    assert lineage["added_structural_context_ids"] == [
        "evidence-2",
        "evidence-3",
    ]
    assert lineage["expanded_evidence_ids"] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
    ]
    assert [item.evidence_id for item in candidate.evidence] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
    ]
    assert candidate.claims[0].evidence_ids == ("evidence-1",)


def test_protocol_v2_accepts_table_action_with_threshold_and_header(
    tmp_path: Path,
) -> None:
    payload = _nonmapping_input_payload()
    payload["context"] = {
        "workflow": "monitoring_protocol_preparation_v2",
        "evidence_packet_version": "monitoring_protocol_evidence_packet_v3",
        "topic_id": "safety_assessment",
        "absence_assertion_authority": "none",
        "detected_source_conflicts": [],
        "candidate_fact_types": ["safety_assessment", "aesi_definition"],
    }
    structures = [
        (
            "48小时内复查并暂停研究药物。",
            ["primary_match", "table_row_context"],
            2,
            1,
        ),
        ("ALT或AST>3×ULN。", ["table_row_context"], 2, 0),
        ("处理措施。", ["table_header"], 0, 1),
    ]
    for item, (quote, roles, row_index, cell_index) in zip(
        payload["evidence_packet"],
        structures,
    ):
        item["quote"] = quote
        item["raw_fields"]["protocol_context"] = {
            "packet_version": "monitoring_protocol_evidence_packet_v3",
            "primary_match": "primary_match" in roles,
            "roles": roles,
            "eligible_for_rule_fact": True,
            "structure": {
                "kind": "table_cell",
                "table_index": 4,
                "row_index": row_index,
                "cell_index": cell_index,
            },
        }

    def complete_table_binding(
        envelope: AiPromptEnvelope,
    ) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        return output

    service = _service(tmp_path, FakeProvider([complete_table_binding]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-complete-table-row-binding",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED


def test_protocol_v2_preserves_cm_ip_boundary(tmp_path: Path) -> None:
    payload = _protocol_v2_conflict_input_payload()
    payload["context"].update(
        {
            "topic_id": "concomitant_medication_policy",
            "detected_source_conflicts": [],
        }
    )

    def ip_as_cm(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"][
            "required_actions"
        ] = ["停用研究药物"]
        return output

    service = _service(
        tmp_path,
        FakeProvider([ip_as_cm, ip_as_cm]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-cm-ip-boundary",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert "CM protocol candidates" in result.job.failure_message


def test_cross_table_task_rejects_pseudo_second_domain(
    tmp_path: Path,
) -> None:
    def one_domain_only(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope, candidate_count=2)
        for candidate in output["candidates"]:
            candidate["structured_payload"]["domains"] = [
                "AE",
                "medication_compliance",
            ]
            candidate["structured_payload"]["evidence_ids"] = ["evidence-1"]
        return output

    service = _service(
        tmp_path,
        FakeProvider([one_domain_only, one_domain_only]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_instance_id="riskinst_private_001",
        ),
        business_key="reject-pseudo-domain",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "two actual source domains" in result.job.failure_message


def test_cross_table_task_requires_two_to_three_candidates(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        FakeProvider(
            [
                lambda envelope: _valid_output(envelope, candidate_count=1),
                lambda envelope: _valid_output(envelope, candidate_count=1),
            ]
        ),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(),
        business_key="cross-table-candidate-count",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_monitoring_ai_rejects_generic_pending_approval_language(
    tmp_path: Path,
) -> None:
    def pending_approval(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["text"] = "该内容仍待批准。"
        return output

    service = _service(
        tmp_path,
        FakeProvider([pending_approval, pending_approval]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(),
        business_key="reject-pending-approval",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_non_mapping_evidence_packet_is_system_owned_and_source_bound(
    tmp_path: Path,
) -> None:
    invalid_packet = _nonmapping_input_payload(
        risk_context={"risk_id": "risk-001"},
    )
    invalid_packet["evidence_packet"][0]["source_content_sha256"] = "d" * 64
    service = _service(tmp_path, FakeProvider([_valid_output]))

    with pytest.raises(ValueError, match="exact input revision"):
        service.submit_task(
            project_id="project-alpha",
            task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            input_revision=_revision(),
            input_payload=invalid_packet,
            business_key="mismatched-evidence-packet",
        )

    def provider_invents_evidence(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        payload = envelope.payload.get("input_payload")
        if payload is None:
            payload = envelope.payload["original_task"]["input_payload"]
        output["candidates"][0]["evidence"] = [
            payload["evidence_packet"][0]
        ]
        return output

    provider = FakeProvider(
        [provider_invents_evidence, provider_invents_evidence]
    )
    service = _service(tmp_path / "invented", provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_context={"risk_id": "risk-001"},
        ),
        business_key="invented-evidence",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"


def test_query_candidate_count_is_repaired_once_then_fails(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            lambda envelope: _valid_output(envelope, candidate_count=1),
            lambda envelope: _valid_output(envelope, candidate_count=1),
        ]
    )
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
        input_revision=_revision(),
        input_payload=_nonmapping_input_payload(
            risk_context={"risk_id": "risk-001"},
        ),
        business_key="query-risk-001",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert len(provider.envelopes) == 2


def test_protocol_v2_provider_envelope_uses_focused_evidence_view(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_conflict_input_payload()
    payload["context"]["detected_source_conflicts"] = []
    payload["context"]["instruction"] = "仅结构化本证据包中的方案原文。"
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    job = service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-focused-view",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    envelope_payload = provider.envelopes[0].payload["input_payload"]
    focused_ids = [
        item["evidence_id"]
        for item in envelope_payload["evidence_packet"]
    ]
    assert focused_ids == ["evidence-1", "evidence-2"]
    focus = envelope_payload["context"]["provider_evidence_focus"]
    assert focus["scope"] == "focused_structural_bundles"
    assert focus["full_document_coverage_asserted"] is False
    assert focus["retained_evidence_count"] == 2
    assert focus["source_evidence_count"] == 3
    assert focus["max_evidence_ids_per_candidate"] == 50
    assert (
        envelope_payload["context"]["retrieval_scope"]
        == "focused_structural_bundles"
    )
    assert "不得超过 50 个" in envelope_payload["context"]["instruction"]
    persisted = service.repository.input_payload(
        job.project_id,
        job.job_id,
    )
    assert len(persisted["evidence_packet"]) == 3
    assert "provider_evidence_focus" not in persisted["context"]
    candidate = service.repository.candidates(
        job.project_id,
        job.job_id,
    )[0]
    assert [item.evidence_id for item in candidate.evidence] == ["evidence-1"]


def test_protocol_v2_repair_envelope_reuses_focused_view_and_carries_budget(
    tmp_path: Path,
) -> None:
    def over_budget_first(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            f"evidence-{index}" for index in range(1, 61)
        ]
        return output

    payload = _protocol_v2_conflict_input_payload()
    payload["context"]["detected_source_conflicts"] = []
    provider = FakeProvider([over_budget_first, _valid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-focused-repair",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    repair_payload = provider.envelopes[1].payload
    repair_evidence = repair_payload["original_task"]["input_payload"][
        "evidence_packet"
    ]
    assert [item["evidence_id"] for item in repair_evidence] == [
        "evidence-1",
        "evidence-2",
    ]
    constraints = repair_payload["protocol_evidence_constraints"]
    assert constraints["max_evidence_ids_per_candidate"] == 50
    assert "same-row" in constraints["structure_bindings"]
    assert "不得超过 50 个" in constraints["instruction"]
    validation_errors = provider.envelopes[1].payload.get(
        "validation_errors",
        "",
    )
    assert any(
        phrase in str(validation_errors)
        for phrase in ("exceed 50", "max_length", "at most 50")
    )


def _over_budget_protocol_input_payload() -> Dict[str, Any]:
    payload = _nonmapping_input_payload()
    payload["evidence_packet"] = [
        {
            "evidence_id": f"evidence-{index}",
            "source_entry_id": "source-listing",
            "source_content_sha256": SOURCE_HASH,
            "locator": f"docx:paragraph:{index}",
            "quote": f"方案原文段落 {index}。",
            "raw_fields": {
                "source_id": f"span-{index}",
                "source_type": "protocol_docx_paragraph",
                "protocol_context": {
                    "packet_version": (
                        "monitoring_protocol_evidence_packet_v3"
                    ),
                    "primary_match": True,
                    "roles": ["primary_match"],
                    "parent_match_source_ids": [f"span-{index}"],
                    "structure": {
                        "kind": "paragraph",
                        "paragraph_index": index,
                    },
                },
            },
        }
        for index in range(1, 71)
    ]
    payload["context"] = {
        "workflow": "monitoring_protocol_preparation_v2",
        "evidence_packet_version": (
            "monitoring_protocol_evidence_packet_v3"
        ),
        "topic_id": "safety_assessment",
        "absence_assertion_authority": "none",
        "detected_source_conflicts": [
            {
                "conflict_id": "protocol_conflict_budget",
                "object_scope": "investigational_product",
                "action": "stop",
                "modalities": ["required", "optional"],
                "status": "requires_user_resolution",
                "evidence_ids": [
                    f"evidence-{index}" for index in range(21, 71)
                ],
            }
        ],
        "candidate_fact_types": ["safety_assessment", "aesi_definition"],
    }
    return payload


def test_protocol_v2_rejects_structured_evidence_over_budget(
    tmp_path: Path,
) -> None:
    def over_budget(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            f"evidence-{index}" for index in range(1, 21)
        ]
        output["candidates"][0]["structured_payload"]["source_conflicts"] = [
            {
                "conflict_id": "protocol_conflict_budget",
                "action": "stop",
                "modalities": ["required", "optional"],
                "status": "requires_user_resolution",
                "evidence_ids": [
                    f"evidence-{index}" for index in range(21, 71)
                ],
            }
        ]
        return output

    provider = FakeProvider([over_budget, over_budget])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_over_budget_protocol_input_payload(),
        business_key="protocol-v2-over-budget",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "exceed 50" in result.job.failure_message
    assert len(provider.envelopes) == 2


def test_protocol_v2_within_budget_completes_with_focused_table_bundle(
    tmp_path: Path,
) -> None:
    payload = _nonmapping_input_payload()
    payload["context"] = {
        "workflow": "monitoring_protocol_preparation_v2",
        "evidence_packet_version": (
            "monitoring_protocol_evidence_packet_v3"
        ),
        "topic_id": "efficacy_assessment",
        "absence_assertion_authority": "none",
        "detected_source_conflicts": [],
        "candidate_fact_types": ["efficacy_assessment"],
    }
    structures = [
        (
            "48小时内复查并暂停研究药物。",
            ["primary_match", "table_row_context"],
            2,
            1,
        ),
        ("ALT或AST>3×ULN。", ["table_row_context"], 2, 0),
        ("处理措施。", ["table_header"], 0, 1),
        ("不属于本束的邻接段落。", ["adjacent_paragraph"], None, None),
    ]
    for item, (quote, roles, row_index, cell_index) in zip(
        payload["evidence_packet"],
        structures,
    ):
        item["quote"] = quote
        item["raw_fields"]["protocol_context"] = {
            "packet_version": "monitoring_protocol_evidence_packet_v3",
            "primary_match": "primary_match" in roles,
            "roles": roles,
            "eligible_for_rule_fact": True,
            "structure": (
                {
                    "kind": "table_cell",
                    "table_index": 4,
                    "row_index": row_index,
                    "cell_index": cell_index,
                }
                if row_index is not None
                else {"kind": "paragraph", "paragraph_index": 9}
            ),
        }

    def complete_table_binding(
        envelope: AiPromptEnvelope,
    ) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        return output

    provider = FakeProvider([complete_table_binding])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-focused-table-completion",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    focused_ids = [
        item["evidence_id"]
        for item in provider.envelopes[0].payload["input_payload"][
            "evidence_packet"
        ]
    ]
    assert focused_ids == ["evidence-1", "evidence-2", "evidence-3"]


def _protocol_v2_payload(
    items: Sequence[Dict[str, Any]],
    *,
    topic_id: str = "safety_assessment",
    conflicts: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    def with_context(item: Dict[str, Any]) -> Dict[str, Any]:
        protocol_context: Dict[str, Any] = {
            "packet_version": (
                "monitoring_protocol_evidence_packet_v3"
            ),
            "primary_match": "primary_match" in item["roles"],
            "roles": list(item["roles"]),
            "parent_match_source_ids": list(item.get("parents", ())),
            "eligible_for_rule_fact": True,
            "structure": item["structure"],
        }
        if item.get("bundle_id"):
            protocol_context["list_bundle_id"] = item["bundle_id"]
        return {
            "evidence_id": item["evidence_id"],
            "source_entry_id": "source-listing",
            "source_content_sha256": SOURCE_HASH,
            "locator": item["locator"],
            "quote": item["quote"],
            "raw_fields": {
                "source_id": f"span-{item['evidence_id']}",
                "source_type": "protocol_docx_paragraph",
                "protocol_context": protocol_context,
            },
        }

    return {
        "evidence_packet": [with_context(item) for item in items],
        "context": {
            "workflow": "monitoring_protocol_preparation_v2",
            "evidence_packet_version": (
                "monitoring_protocol_evidence_packet_v3"
            ),
            "topic_id": topic_id,
            "absence_assertion_authority": "none",
            "detected_source_conflicts": list(conflicts),
            "candidate_fact_types": ["safety_assessment", "aesi_definition"],
        },
    }


def _table_cell(
    evidence_id: str,
    quote: str,
    *,
    table_index: int,
    row_index: int,
    cell_index: int,
    roles: Sequence[str] = ("table_row_context",),
) -> Dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator": (
            f"docx:table:{table_index}:row:{row_index}:"
            f"cell:{cell_index}:paragraph:1"
        ),
        "quote": quote,
        "roles": roles,
        "structure": {
            "kind": "table_cell",
            "table_index": table_index,
            "row_index": row_index,
            "cell_index": cell_index,
        },
    }


@pytest.mark.parametrize("field_name", ["table_index", "row_index"])
def test_protocol_output_validation_rejects_boolean_table_indices(
    field_name: str,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "处理措施。",
                table_index=4,
                row_index=2,
                cell_index=0,
            )
        ]
    )
    evidence = payload["evidence_packet"][0]
    evidence["raw_fields"]["protocol_context"]["structure"][field_name] = True
    evidence_by_id = {evidence["evidence_id"]: evidence}

    with pytest.raises(
        monitoring_ai_service_module.MonitoringAiOutputValidationError,
        match="typed table identity",
    ):
        MonitoringAiService._validate_protocol_structure_bindings(
            {"evidence-1"}, evidence_by_id
        )


def _paragraph(
    evidence_id: str,
    quote: str,
    *,
    paragraph_index: int,
    roles: Sequence[str] = ("primary_match",),
    parents: Sequence[str] = (),
    bundle_id: str = "",
) -> Dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "locator": f"docx:paragraph:{paragraph_index}",
        "quote": quote,
        "roles": roles,
        "parents": parents,
        "bundle_id": bundle_id,
        "structure": {
            "kind": "paragraph",
            "paragraph_index": paragraph_index,
        },
    }


def test_protocol_v2_repair_list_item_adds_unique_title_not_siblings(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "禁止使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
            _paragraph(
                "evidence-2",
                "（1）其他试验用药；",
                paragraph_index=31,
                roles=["list_item"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
            _paragraph(
                "evidence-3",
                "（2）免疫抑制剂；",
                paragraph_index=32,
                roles=["list_item"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
        ]
    )

    def item_cited(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-2"
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-2"
        ]
        return output

    service = _service(tmp_path, FakeProvider([item_cited]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-repair-list-item",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["evidence_ids"] == [
        "evidence-1",
        "evidence-2",
    ]
    lineage = candidate.structured_payload["repair_lineage"]
    assert lineage["original_evidence_ids"] == ["evidence-2"]
    assert lineage["added_structural_context_ids"] == ["evidence-1"]
    assert [item.evidence_id for item in candidate.evidence] == [
        "evidence-1",
        "evidence-2",
    ]
    assert candidate.claims[0].evidence_ids == ("evidence-2",)


def test_protocol_v2_rejects_provider_forged_repair_lineage(
    tmp_path: Path,
) -> None:
    def forged_lineage(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["repair_lineage"] = {
            "schema_version": "monitoring_protocol_structural_repair_v2",
            "original_evidence_ids": [],
        }
        return output

    service = _service(
        tmp_path,
        FakeProvider([forged_lineage, forged_lineage]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=_protocol_v2_conflict_input_payload(),
        business_key="protocol-v2-forged-lineage",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "repair lineage" in result.job.failure_message


def test_protocol_v2_rejects_cross_row_table_union(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT>5×ULN。",
                table_index=4,
                row_index=3,
                cell_index=0,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ]
    )

    def cross_row(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        return output

    service = _service(tmp_path, FakeProvider([cross_row, cross_row]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-cross-row-union",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "across rows" in result.job.failure_message


def test_protocol_v2_rejects_title_from_other_list(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "允许使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
                parents=["matched-a"],
                bundle_id="src-list-a",
            ),
            _paragraph(
                "evidence-2",
                "（1）外用糖皮质激素；",
                paragraph_index=31,
                roles=["list_item"],
                parents=["matched-a"],
                bundle_id="src-list-a",
            ),
            _paragraph(
                "evidence-3",
                "禁止使用以下治疗：",
                paragraph_index=32,
                roles=["list_title"],
                parents=["matched-b"],
                bundle_id="src-list-b",
            ),
            _paragraph(
                "evidence-4",
                "（1）免疫抑制剂；",
                paragraph_index=33,
                roles=["list_item"],
                parents=["matched-b"],
                bundle_id="src-list-b",
            ),
        ]
    )

    def mixed_lists(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-4",
        ]
        return output

    service = _service(tmp_path, FakeProvider([mixed_lists, mixed_lists]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-mixed-lists",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "from another list" in result.job.failure_message


def test_protocol_v2_rejects_header_only_evidence(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "触发条件。",
                table_index=4,
                row_index=0,
                cell_index=0,
                roles=["table_header"],
            ),
            _table_cell(
                "evidence-2",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
            _paragraph("evidence-3", "普通段落。", paragraph_index=9),
        ]
    )

    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-header-only",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "header-only" in result.job.failure_message


def test_protocol_v2_title_only_list_claim_fails_closed(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "禁止使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
            _paragraph(
                "evidence-2",
                "（1）其他试验用药；",
                paragraph_index=31,
                roles=["list_item"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
            _paragraph(
                "evidence-3",
                "（2）免疫抑制剂；",
                paragraph_index=32,
                roles=["list_item"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
        ]
    )

    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-title-only",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "selected entry" in result.job.failure_message


def test_protocol_v2_rejects_repair_expansion_over_budget(
    tmp_path: Path,
) -> None:
    cells = [
        _table_cell(
            f"evidence-{index}",
            f"单元格 {index}。",
            table_index=4,
            row_index=2,
            cell_index=index,
        )
        for index in range(1, 56)
    ]
    payload = _protocol_v2_payload(cells)

    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-expansion-over-budget",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "exceed 50" in result.job.failure_message


def test_protocol_v2_rejects_out_of_packet_structured_evidence(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [_paragraph("evidence-1", "普通段落。", paragraph_index=9)]
    )

    def out_of_packet(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-99"
        ]
        return output

    service = _service(tmp_path, FakeProvider([out_of_packet, out_of_packet]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-out-of-packet",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "frozen packet" in result.job.failure_message


def test_protocol_v2_medical_gates_reject_after_structural_expansion(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ],
        topic_id="concomitant_medication_policy",
    )

    def ip_as_cm(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"][
            "required_actions"
        ] = ["停用研究药物"]
        return output

    service = _service(tmp_path, FakeProvider([ip_as_cm, ip_as_cm]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-gate-after-expansion",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "CM protocol candidates" in result.job.failure_message


def test_protocol_v2_rejects_empty_list_ancestry(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "禁止使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
            ),
            _paragraph(
                "evidence-2",
                "（1）其他试验用药；",
                paragraph_index=31,
                roles=["list_item"],
            ),
        ]
    )

    service = _service(tmp_path, FakeProvider([_valid_output, _valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-empty-list-ancestry",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "typed list identity" in result.job.failure_message


def test_protocol_v2_claim_only_table_id_is_closed_and_validated(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
            _paragraph("evidence-4", "普通段落条款。", paragraph_index=9),
        ]
    )

    def claim_cites_cell(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-4"
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1"
        ]
        return output

    service = _service(tmp_path, FakeProvider([claim_cites_cell]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-claim-only-table-id",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["evidence_ids"] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
        "evidence-4",
    ]
    lineage = candidate.structured_payload["repair_lineage"]
    assert lineage["original_evidence_ids"] == ["evidence-4", "evidence-1"]
    assert lineage["added_structural_context_ids"] == [
        "evidence-2",
        "evidence-3",
    ]
    assert [item.evidence_id for item in candidate.evidence] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
        "evidence-4",
    ]
    assert candidate.claims[0].evidence_ids == ("evidence-1",)


def test_protocol_v2_claim_only_header_fails(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "触发条件。",
                table_index=4,
                row_index=0,
                cell_index=0,
                roles=["table_header"],
            ),
            _table_cell(
                "evidence-2",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
            _paragraph("evidence-3", "普通段落条款。", paragraph_index=9),
        ]
    )

    def claim_cites_header(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-3"
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1"
        ]
        return output

    service = _service(tmp_path, FakeProvider([claim_cites_header, claim_cites_header]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-claim-only-header",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "header-only" in result.job.failure_message


def test_protocol_v2_claim_header_without_data_row_fails(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ]
    )

    def header_only_claim(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-3"
        ]
        return output

    service = _service(tmp_path, FakeProvider([header_only_claim, header_only_claim]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-claim-header-only",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "data-row cell" in result.job.failure_message


def test_protocol_v2_claim_title_without_entry_fails(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "禁止使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
            _paragraph(
                "evidence-2",
                "（1）其他试验用药；",
                paragraph_index=31,
                roles=["list_item"],
                parents=["matched-1"],
                bundle_id="src-list-1",
            ),
        ]
    )

    def title_only_claim(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1"
        ]
        return output

    service = _service(tmp_path, FakeProvider([title_only_claim, title_only_claim]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-claim-title-only",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "provider-selected entry" in result.job.failure_message


def test_protocol_candidate_identity_binds_normalized_repair_payload(
    tmp_path: Path,
) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ]
    )
    service = _service(tmp_path, FakeProvider([_valid_output]))
    job = service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-identity-normalized",
    )
    raw_candidate = {
        "candidate_type": "protocol_clause_structure",
        "title": "监查候选 1",
        "text": "基于授权证据提出，需医学经理复核。",
        "structured_payload": {
            "clause_id": "clause-1",
            "fact_type": "safety_assessment",
            "subject_scope": "所有已随机受试者",
            "conditions": ["满足方案规定条件"],
            "time_windows": ["访视窗内"],
            "thresholds": [],
            "exceptions": [],
            "required_actions": ["医学复核"],
            "evidence_ids": ["evidence-1"],
        },
        "claims": [
            {
                "claim_id": "claim-1",
                "kind": "recommendation",
                "text": "该候选需要结合完整项目上下文复核。",
                "confidence": 0.82,
                "uncertainty": "尚未获得医学经理最终判断。",
                "user_action": "请确认或修订候选。",
                "evidence_ids": ["evidence-1"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "source_entry_id": "source-listing",
                "source_content_sha256": SOURCE_HASH,
                "locator": "docx:table:4:row:2:cell:1:paragraph:1",
                "quote": "48小时内复查并暂停研究药物。",
                "raw_fields": {},
            }
        ],
    }
    candidate_model = (
        monitoring_ai_service_module._ProviderCandidate.model_validate(
            raw_candidate
        )
    )
    normalized = {
        **candidate_model.structured_payload,
        "evidence_ids": ["evidence-1", "evidence-2", "evidence-3"],
        "repair_lineage": {
            "schema_version": "monitoring_protocol_structural_repair_v2",
            "original_evidence_ids": ["evidence-1"],
            "added_structural_context_ids": ["evidence-2", "evidence-3"],
            "expanded_evidence_ids": [
                "evidence-1",
                "evidence-2",
                "evidence-3",
            ],
            "bundle_bindings": [
                {
                    "kind": "table",
                    "table_index": 4,
                    "row_index": 2,
                    "row_evidence_ids": ["evidence-1", "evidence-2"],
                    "header_evidence_ids": ["evidence-3"],
                }
            ],
        },
    }
    built = MonitoringAiService._candidate_from_provider(
        job,
        candidate_model,
        normalized,
        1,
        service.repository.clock(),
    )
    raw_dump = candidate_model.model_dump(mode="json")
    raw_seed = {
        "job_id": job.job_id,
        "index": 1,
        "candidate": raw_dump,
    }
    normalized_seed = {
        "job_id": job.job_id,
        "index": 1,
        "candidate": {
            **raw_dump,
            "structured_payload": normalized,
        },
    }
    altered = dict(normalized)
    altered["repair_lineage"] = dict(normalized["repair_lineage"])
    altered["repair_lineage"]["schema_version"] = (
        "monitoring_protocol_structural_repair_v9"
    )
    altered_seed = {
        "job_id": job.job_id,
        "index": 1,
        "candidate": {
            **raw_dump,
            "structured_payload": altered,
        },
    }
    assert built.candidate_id == (
        "moncand_"
        + monitoring_ai_service_module.content_sha256(normalized_seed)[:28]
    )
    assert built.candidate_id != (
        "moncand_"
        + monitoring_ai_service_module.content_sha256(raw_seed)[:28]
    )
    assert built.candidate_id != (
        "moncand_"
        + monitoring_ai_service_module.content_sha256(altered_seed)[:28]
    )


def test_protocol_repair_lineage_is_typed(tmp_path: Path) -> None:
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "48小时内复查并暂停研究药物。",
                table_index=4,
                row_index=2,
                cell_index=1,
                roles=["primary_match", "table_row_context"],
            ),
            _table_cell(
                "evidence-2",
                "ALT或AST>3×ULN。",
                table_index=4,
                row_index=2,
                cell_index=0,
            ),
            _table_cell(
                "evidence-3",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
        ]
    )

    service = _service(tmp_path, FakeProvider([_valid_output]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="protocol-v2-typed-lineage",
    )

    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    validated = monitoring_ai_service_module._ProtocolClausePayload.model_validate(
        candidate.structured_payload
    )
    assert validated.repair_lineage is not None
    assert validated.repair_lineage.schema_version == (
        "monitoring_protocol_structural_repair_v2"
    )
    assert validated.repair_lineage.original_evidence_ids == [
        "evidence-1"
    ]
    assert validated.repair_lineage.added_structural_context_ids == [
        "evidence-2",
        "evidence-3",
    ]
    binding = validated.repair_lineage.bundle_bindings[0]
    assert binding.kind == "table"
    assert binding.table_index == 4
    assert binding.row_index == 2
    malformed = dict(candidate.structured_payload)
    malformed["repair_lineage"] = {
        **candidate.structured_payload["repair_lineage"],
        "bundle_bindings": [
            {
                "kind": "table-row",
                "table_index": 4,
                "row_index": 2,
                "row_evidence_ids": [],
                "header_evidence_ids": [],
            }
        ],
    }
    with pytest.raises(ValidationError):
        monitoring_ai_service_module._ProtocolClausePayload.model_validate(
            malformed
        )


def _visit_v3_payload(
    items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = _protocol_v2_payload(
        items,
        topic_id="visit_window_and_order",
    )
    payload["context"]["candidate_fact_types"] = [
        "visit_schedule",
        "visit_window",
    ]
    return payload


def test_v3_visit_heading_body_pair_passes_closure_then_topic_gate_fails(
    tmp_path: Path,
) -> None:
    """N9: paragraphs 1171-1172 pass identity closure alone; the same
    paragraphs combined with IP restart/BSA claims fail the visit topic gate.
    """
    items = [
        _paragraph(
            "evidence-1",
            "计划外访视：",
            paragraph_index=1171,
        ),
        _paragraph(
            "evidence-2",
            "研究者应根据受试者情况安排计划外访视。",
            paragraph_index=1172,
        ),
    ]
    payload = _visit_v3_payload(items)

    def plain_visit(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        return output

    service = _service(tmp_path, FakeProvider([plain_visit]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-visit-closure",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED

    def mixed_visit(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = plain_visit(envelope)
        output["candidates"][0]["structured_payload"]["required_actions"] = [
            "BSA>20%时复发后重启研究药物"
        ]
        return output

    service = _service(tmp_path, FakeProvider([mixed_visit, mixed_visit]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-visit-topic-gate",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert (
        "study-treatment or concomitant-medication actions"
        in result.job.failure_message
    )


def test_v3_visit_candidate_requires_exactly_one_action_family(
    tmp_path: Path,
) -> None:
    """N11: a visit candidate must contain exactly one of the schedule/
    window, reschedule/makeup or unscheduled-visit families."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在允许时间窗内完成。",
                paragraph_index=110,
            ),
            _paragraph(
                "evidence-2",
                "漏访的受试者应安排补访。",
                paragraph_index=111,
            ),
            _paragraph(
                "evidence-3",
                "计划外访视应单独记录。",
                paragraph_index=112,
            ),
        ]
    )

    def mixed_families(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        output["candidates"][0]["text"] = "时间窗、补访与计划外访视合并条款。"
        return output

    service = _service(tmp_path, FakeProvider([mixed_families, mixed_families]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-visit-mixed-families",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in result.job.failure_message

    def single_family(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1"
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1"
        ]
        output["candidates"][0]["text"] = "仅访视时间窗条款。"
        return output

    service = _service(tmp_path, FakeProvider([single_family]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-visit-single-family",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED


def test_v3_conflict_claim_preserves_exact_evidence_and_permitted_kind(
    tmp_path: Path,
) -> None:
    """N12: a qualifying source-conflict claim keeps the exact evidence set
    and an inference/data_gap kind with uncertainty and user action."""
    payload = _protocol_v2_conflict_input_payload()

    def exact_data_gap(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
        ]
        candidate["structured_payload"]["source_conflicts"] = [
            {
                "conflict_id": "protocol_conflict_stop",
                "action": "stop",
                "modalities": ["required", "optional"],
                "status": "requires_user_resolution",
                "evidence_ids": ["evidence-1", "evidence-2"],
            }
        ]
        candidate["claims"][0].update(
            {
                "kind": "data_gap",
                "text": "原文对同一停药动作存在强制与可选措辞冲突。",
                "uncertainty": "冲突原文均有效，系统不得代替用户裁决。",
                "user_action": "请基于并列原文确认最终执行要求。",
                "evidence_ids": ["evidence-1", "evidence-2"],
            }
        )
        return output

    service = _service(tmp_path, FakeProvider([exact_data_gap]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-exact-conflict",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    conflict = candidate.structured_payload["source_conflicts"][0]
    assert conflict["evidence_ids"] == ["evidence-1", "evidence-2"]
    assert candidate.claims[0].kind.value == "data_gap"
    assert list(candidate.claims[0].evidence_ids) == [
        "evidence-1",
        "evidence-2",
    ]

    def altered_conflict(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = exact_data_gap(envelope)
        output["candidates"][0]["structured_payload"]["source_conflicts"][0][
            "evidence_ids"
        ] = ["evidence-1", "evidence-3"]
        return output

    service = _service(tmp_path, FakeProvider([altered_conflict, altered_conflict]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-altered-conflict",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert "must preserve the exact action" in result.job.failure_message

    def fact_kind_claim(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = exact_data_gap(envelope)
        output["candidates"][0]["claims"][0]["kind"] = "fact"
        return output

    service = _service(tmp_path, FakeProvider([fact_kind_claim, fact_kind_claim]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-fact-kind-conflict",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert "requires an uncertainty claim" in result.job.failure_message


def test_v3_protocol_output_schema_omits_system_generated_evidence(
    tmp_path: Path,
) -> None:
    """N13: ``system_generated_evidence`` stays an instruction outside the
    protocol provider output schema and never appears as a candidate key."""
    payload = _protocol_v2_conflict_input_payload()
    payload["context"]["detected_source_conflicts"] = []
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-schema-cleanup",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED

    import json

    envelope = provider.envelopes[0]
    candidate_schema = envelope.payload["output_schema"]["candidates"][0]
    assert "system_generated_evidence" not in candidate_schema
    assert (
        "system_generated_evidence"
        not in json.dumps(envelope.payload["output_schema"], ensure_ascii=False)
    )
    assert "确定性绑定原始内容" in envelope.system_prompt


def test_v3_one_cell_narrative_row_context_is_lineage_only(
    tmp_path: Path,
) -> None:
    """N14: a one-cell narrative row may add row/header context, but
    server-added context and parent lineage cannot support an unrelated
    claim; the provider anchor stays the only claim anchor."""
    payload = _protocol_v2_payload(
        [
            _table_cell(
                "evidence-1",
                "访视安排。",
                table_index=4,
                row_index=0,
                cell_index=0,
                roles=["table_header"],
            ),
            _table_cell(
                "evidence-2",
                "处理措施。",
                table_index=4,
                row_index=0,
                cell_index=1,
                roles=["table_header"],
            ),
            _table_cell(
                "evidence-3",
                "本中心所有受试者均按方案完成计划访视。",
                table_index=4,
                row_index=2,
                cell_index=0,
                roles=["primary_match", "table_row_context"],
            ),
        ]
    )
    # Causal expansion lineage is recorded but is not a typed identity and
    # can never support a claim.
    payload["evidence_packet"][2]["raw_fields"]["protocol_context"][
        "parent_match_source_ids"
    ] = ["span-unrelated-match"]

    def header_only_claim(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-1"
        ]
        return output

    service = _service(
        tmp_path,
        FakeProvider([header_only_claim, header_only_claim]),
    )
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-header-only-claim",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert (
        "claim table evidence requires a provider-selected data-row cell"
        in result.job.failure_message
    )

    def cell_anchor_claim(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-1",
            "evidence-2",
            "evidence-3",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-3"
        ]
        return output

    service = _service(tmp_path, FakeProvider([cell_anchor_claim]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-cell-anchor-claim",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    candidate = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )[0]
    assert candidate.structured_payload["evidence_ids"] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
    ]
    assert list(candidate.claims[0].evidence_ids) == ["evidence-3"]


def test_v3_protocol_candidate_rejects_disallowed_fact_type(
    tmp_path: Path,
) -> None:
    """Required provider fact_type must belong to the topic's
    candidate_fact_types."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def wrong_fact_type(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"][
            "fact_type"
        ] = "study_treatment_change"
        return output

    service = _service(tmp_path, FakeProvider([wrong_fact_type, wrong_fact_type]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-disallowed-fact-type",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "fact_type is not an allowed topic" in result.job.failure_message


def test_v3_identical_parent_sets_keep_physical_lists_separate(
    tmp_path: Path,
) -> None:
    """Service-level N4: identical parent-match sets must not merge two
    physically different lists into one typed bundle."""
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "允许使用以下药物：",
                paragraph_index=30,
                roles=["list_title"],
                parents=["matched-9"],
                bundle_id="src-list-a",
            ),
            _paragraph(
                "evidence-2",
                "（1）外用糖皮质激素；",
                paragraph_index=31,
                roles=["list_item"],
                parents=["matched-9"],
                bundle_id="src-list-a",
            ),
            _paragraph(
                "evidence-3",
                "禁止使用以下治疗：",
                paragraph_index=32,
                roles=["list_title"],
                parents=["matched-9"],
                bundle_id="src-list-b",
            ),
            _paragraph(
                "evidence-4",
                "（1）免疫抑制剂；",
                paragraph_index=33,
                roles=["list_item"],
                parents=["matched-9"],
                bundle_id="src-list-b",
            ),
        ]
    )

    def mixed_lists(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"][0]["structured_payload"]["evidence_ids"] = [
            "evidence-2",
            "evidence-4",
        ]
        output["candidates"][0]["claims"][0]["evidence_ids"] = [
            "evidence-2",
            "evidence-4",
        ]
        return output

    service = _service(tmp_path, FakeProvider([mixed_lists, mixed_lists]))
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v3-identical-parents-lists",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert "across lists" in result.job.failure_message


def _visit_output(
    envelope: AiPromptEnvelope,
    *,
    text: str,
    title: str = "访视候选",
    subject_scope: str = "所有已随机受试者",
    conditions: Sequence[str] = (),
    time_windows: Sequence[str] = (),
    thresholds: Sequence[str] = (),
    exceptions: Sequence[str] = (),
    required_actions: Sequence[str] = (),
    uncertainty: str = "",
    user_action: str = "",
    evidence_ids: Sequence[str] = ("evidence-1",),
) -> Dict[str, Any]:
    output = _valid_output(envelope)
    candidate = output["candidates"][0]
    candidate["title"] = title
    candidate["text"] = text
    candidate["structured_payload"].update(
        {
            "subject_scope": subject_scope,
            "conditions": list(conditions),
            "time_windows": list(time_windows),
            "thresholds": list(thresholds),
            "exceptions": list(exceptions),
            "required_actions": list(required_actions),
            "evidence_ids": list(evidence_ids),
        }
    )
    candidate["claims"][0]["evidence_ids"] = list(evidence_ids)
    if uncertainty:
        candidate["claims"][0]["uncertainty"] = uncertainty
    if user_action:
        candidate["claims"][0]["user_action"] = user_action
    return output


def _visit_candidate(
    seed_output: Dict[str, Any],
    *,
    index: int,
    title: str,
    text: str,
    evidence_id: str,
    time_windows: Sequence[str] = (),
    required_actions: Sequence[str] = (),
) -> Dict[str, Any]:
    seed_claim = seed_output["candidates"][0]["claims"][0]
    return {
        "candidate_type": "protocol_clause_structure",
        "title": title,
        "text": text,
        "structured_payload": {
            "clause_id": f"clause-c{index}",
            "fact_type": "visit_schedule",
            "subject_scope": "所有已随机受试者",
            "conditions": [],
            "time_windows": list(time_windows),
            "thresholds": [],
            "exceptions": [],
            "required_actions": list(required_actions),
            "evidence_ids": [evidence_id],
        },
        "claims": [
            {
                **seed_claim,
                "claim_id": f"claim-c{index}",
                "evidence_ids": [evidence_id],
            }
        ],
    }


def _run_visit_builder(
    tmp_path: Path,
    payload: Dict[str, Any],
    builders: List[Callable[[AiPromptEnvelope], Dict[str, Any]]],
    business_key: str,
) -> tuple[MonitoringAiJob, FakeProvider]:
    provider = FakeProvider(builders)
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key=business_key,
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    return result.job, provider


@pytest.mark.parametrize(
    "directive",
    (
        "第1天进行首次给药",
        "受试者首次用药",
        "研究者给予研究药物",
        "受试者接受研究药物治疗",
        "使用合并用药控制症状",
        "第2周期开始给药",
        "停药后恢复给药",
        "每天服用研究药物",
        "注射研究药物",
        "复发后重启研究药物",
        "暂停研究药物",
        "增加剂量研究药物",
        "研究药物使用记录",
    ),
)
def test_v7_visit_rejects_ip_cm_administration_and_first_dose_directives(
    tmp_path: Path,
    directive: str,
) -> None:
    """First-dose/IP and CM administration directives fail before family
    classification, including the stop/restart/dose-change variants."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[directive],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-medication",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "study-treatment or concomitant-medication actions"
        in job.failure_message
    )


@pytest.mark.parametrize(
    "token_text",
    (
        "药品发放与回收记录",
        "研究药物分发",
        "药物称重",
        "依从性评估",
        "药代动力学采血",
        "血药浓度监测",
        "PK样本采集",
    ),
)
def test_v7_visit_rejects_dispensing_return_weighing_adherence_pk_tokens(
    tmp_path: Path,
    token_text: str,
) -> None:
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[token_text],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-dispensing-pk",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "dispensing" in job.failure_message


@pytest.mark.parametrize(
    "withdrawal_text",
    (
        "受试者提前退出",
        "退出研究",
        "终止研究",
        "退出试验",
        "撤回同意",
        "撤回知情同意",
        "撤销同意",
        "撤销知情同意",
        "失访",
    ),
)
def test_v7_visit_rejects_withdrawal_and_consent_withdrawal_variants(
    tmp_path: Path,
    withdrawal_text: str,
) -> None:
    """Early-exit, lost follow-up, withdrawal of consent and withdrawal of
    informed-consent variants all fail at the withdrawal topic boundary."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[withdrawal_text],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-withdrawal",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "withdrawal content" in job.failure_message


def test_v7_visit_timing_only_dosing_phrase_is_schedule_not_administration(
    tmp_path: Path,
) -> None:
    """给药前7天内完成计划访视 is a schedule/window reference, not an
    administration directive, and must pass the visit gate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="给药前7天内完成计划访视。",
            time_windows=["访视窗内"],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-timing-control",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v7_visit_last_dose_timing_fails_as_safety_not_first_dose(
    tmp_path: Path,
) -> None:
    """末次给药后28天进行安全性随访 fails as safety follow-up, never as
    first-dose administration: the medication gate must not fire first."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="末次给药后28天进行安全性随访。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-last-dose-timing",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "safety follow-up" in job.failure_message
    assert (
        "study-treatment or concomitant-medication actions"
        not in job.failure_message
    )


@pytest.mark.parametrize(
    "safety_text",
    ("安全性随访", "安全随访电话"),
)
def test_v7_visit_rejects_safety_followup_content(
    tmp_path: Path,
    safety_text: str,
) -> None:
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[safety_text],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-safety",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert "safety follow-up" in job.failure_message


@pytest.mark.parametrize(
    "collection_text",
    (
        "询问并记录受试者的AE和合并用药情况",
        "记录不良事件",
        "收集AE",
        "询问合并用药",
        "记录合并用药情况",
    ),
)
def test_v7_visit_rejects_distributed_ae_cm_collection_wording(
    tmp_path: Path,
    collection_text: str,
) -> None:
    """Distributed 询问并记录……AE、合并用药 wording fails at the AE/CM
    collection topic boundary."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[collection_text],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-collection",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert "AE or CM" in job.failure_message


def test_v7_visit_collection_false_positive_control(
    tmp_path: Path,
) -> None:
    """A visit narrative that asks about the visit itself, without AE/CM
    collection objects, must not trigger the collection gate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视时研究者询问受试者本次访视感受。",
            time_windows=["访视窗内"],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-collection-control",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    ("family_text", "time_windows"),
    (
        ("计划访视应在允许时间窗内完成。", ("访视窗内",)),
        ("漏访的受试者应安排补访。", ()),
        ("研究者应根据受试者情况安排计划外访视。", ()),
        ("计划外访视安排由研究者确认。", ()),
    ),
)
def test_v7_visit_pure_families_pass(
    tmp_path: Path,
    family_text: str,
    time_windows: Sequence[str],
) -> None:
    """Pure schedule, pure reschedule and pure unscheduled candidates each
    pass; 计划外访视安排 must not double-match schedule and unscheduled."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=family_text,
            time_windows=time_windows,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-pure-family",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    ("family_text", "time_windows"),
    (
        ("时间窗与补访合并条款。", ()),
        ("计划访视与计划外访视分开记录。", ()),
        ("时间窗、补访与计划外访视合并条款。", ()),
        ("仅汇总监查说明。", ()),
    ),
)
def test_v7_visit_combined_or_missing_families_reject(
    tmp_path: Path,
    family_text: str,
    time_windows: Sequence[str],
) -> None:
    """Operative schedule+reschedule and schedule+unscheduled reject; zero
    families reject; every rejection keeps the exactly-one-family gate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=family_text,
            time_windows=time_windows,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-family-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message


def test_v7_visit_family_classification_is_operative_only(
    tmp_path: Path,
) -> None:
    """Claim uncertainty and user_action cannot create a topic violation or a
    visit action family: the fixture carries reschedule and unscheduled
    content only in review guidance and must pass."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            uncertainty="计划外访视安排与补访安排均需记录。",
            user_action="请医学经理确认计划外访视和补访记录要求。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-operative-only",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def _assert_error_order(
    failure_message: str,
    earlier: str,
    later: str,
) -> None:
    assert earlier in failure_message
    assert later in failure_message
    assert failure_message.index(earlier) < failure_message.index(later)


@pytest.mark.parametrize(
    (
        "family_text",
        "required_actions",
        "first_error",
        "second_error",
        "third_error",
    ),
    (
        # C1/C2 shape: first-dose IP administration plus operative
        # schedule+reschedule -> medication before family.
        (
            "时间窗与补访合并条款。",
            ("第1天进行首次给药",),
            "study-treatment or concomitant-medication actions",
            "exactly one visit action family",
            None,
        ),
        # C3 shape: withdrawal, safety follow-up, zero families -> ordered
        # withdrawal, safety, family.
        (
            "受试者撤回知情同意后需进行安全性随访。",
            (),
            "withdrawal content",
            "safety follow-up",
            "exactly one visit action family",
        ),
        # C4 shape: withdrawal plus operative schedule+unscheduled ->
        # withdrawal before family.
        (
            "提前退出受试者安排计划访视与计划外访视。",
            (),
            "withdrawal content",
            "exactly one visit action family",
            None,
        ),
        # C5 shape: first-dose administration only -> medication before the
        # zero-family rejection.
        (
            "仅记录首次给药安排。",
            (),
            "study-treatment or concomitant-medication actions",
            "exactly one visit action family",
            None,
        ),
    ),
)
def test_v7_visit_error_precedence_is_documented_and_ordered(
    tmp_path: Path,
    family_text: str,
    required_actions: Sequence[str],
    first_error: str,
    second_error: str,
    third_error: str | None,
) -> None:
    """C1-C5-shaped regressions keep the documented first/ordered failures:
    medication, dispensing/PK, withdrawal, safety, collection, family."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=family_text,
            required_actions=required_actions,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-precedence",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    _assert_error_order(job.failure_message, first_error, second_error)
    if third_error is not None:
        _assert_error_order(job.failure_message, second_error, third_error)


def test_v7_visit_multi_candidate_repair_receives_complete_indexed_errors(
    tmp_path: Path,
) -> None:
    """All invalid candidates are reported once, with stable candidate
    index/title and ordered per-candidate errors, in the single controlled
    repair; a valid repair completes with exactly one candidate persisted."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            ),
            _paragraph(
                "evidence-2",
                "漏访受试者安排补访。",
                paragraph_index=101,
            ),
            _paragraph(
                "evidence-3",
                "受试者提前退出安排。",
                paragraph_index=102,
            ),
        ]
    )

    def invalid_multi(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"] = [
            _visit_candidate(
                output,
                index=1,
                title="盲态第2周访视",
                text="时间窗与补访合并条款。",
                evidence_id="evidence-1",
                time_windows=("访视窗内",),
                required_actions=("第1天进行首次给药",),
            ),
            _visit_candidate(
                output,
                index=2,
                title="开放期第12周访视",
                text="提前退出受试者安排计划访视与计划外访视。",
                evidence_id="evidence-2",
            ),
            _visit_candidate(
                output,
                index=3,
                title="安全性随访电话",
                text="受试者撤回知情同意后需进行安全性随访。",
                evidence_id="evidence-3",
            ),
        ]
        return output

    def valid_repair(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
        )

    provider = FakeProvider([invalid_multi, valid_repair])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-visit-multi-candidate",
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    # Exactly one initial call plus one controlled repair.
    assert len(provider.envelopes) == 2
    repair = provider.envelopes[1]
    assert repair.prompt_version == (
        "monitoring-protocol-clause-structuring-v12:json-repair-1"
    )
    validation_errors = repair.payload["validation_errors"]
    assert "candidate 1 (盲态第2周访视):" in validation_errors
    assert "candidate 2 (开放期第12周访视):" in validation_errors
    assert "candidate 3 (安全性随访电话):" in validation_errors
    c1_block = validation_errors[
        validation_errors.index("candidate 1 (盲态第2周访视):") :
    ]
    c2_block = validation_errors[
        validation_errors.index("candidate 2 (开放期第12周访视):") :
    ]
    c3_block = validation_errors[
        validation_errors.index("candidate 3 (安全性随访电话):") :
    ]
    _assert_error_order(
        c1_block,
        "study-treatment or concomitant-medication actions",
        "exactly one visit action family",
    )
    _assert_error_order(
        c2_block,
        "withdrawal content",
        "exactly one visit action family",
    )
    _assert_error_order(
        c3_block,
        "withdrawal content",
        "safety follow-up",
    )
    _assert_error_order(
        c3_block,
        "safety follow-up",
        "exactly one visit action family",
    )
    candidates = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )
    assert len(candidates) == 1


def test_v7_visit_mixed_valid_invalid_output_persists_nothing(
    tmp_path: Path,
) -> None:
    """One invalid candidate fails the whole response atomically: zero
    candidates persist and the repair sees the candidate-indexed error."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            ),
            _paragraph(
                "evidence-2",
                "计划访视应在允许时间窗内完成。",
                paragraph_index=101,
            ),
        ]
    )

    def mixed(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"] = [
            _visit_candidate(
                output,
                index=1,
                title="计划访视候选",
                text="计划访视应在允许时间窗内完成。",
                evidence_id="evidence-1",
                time_windows=("访视窗内",),
            ),
            _visit_candidate(
                output,
                index=2,
                title="首次给药候选",
                text="仅记录首次给药安排。",
                evidence_id="evidence-2",
            ),
        ]
        return output

    provider = FakeProvider([mixed, mixed])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-visit-mixed-atomic",
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    # Terminal after exactly one controlled repair; nothing persists.
    assert len(provider.envelopes) == 2
    assert "candidate 2 (首次给药候选):" in result.job.failure_message
    assert "study-treatment or concomitant-medication actions" in (
        result.job.failure_message
    )
    assert (
        service.repository.candidates("project-alpha", result.job.job_id)
        == ()
    )


def test_v12_protocol_prompt_version_and_visit_instructions(
    tmp_path: Path,
) -> None:
    """The visit topic prompt is exactly v12 and carries the whitelist,
    forbidden-topic, one-family/splitting, reschedule semantic-role,
    reference-complement, source-faithfulness and study-completion/end
    exclusions plus the excluded-family-name repetition prohibitions."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v10-visit-prompt",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED

    assert (
        monitoring_ai_service_module.PROMPT_VERSION_BY_TASK[
            MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
        ]
        == "monitoring-protocol-clause-structuring-v12"
    )
    envelope = provider.envelopes[0]
    assert envelope.prompt_version == (
        "monitoring-protocol-clause-structuring-v12"
    )
    assert "恰好一个访视动作家族" in envelope.system_prompt
    assert "首次给药" in envelope.system_prompt
    assert "计划外访视" in envelope.system_prompt
    assert "改期/补访" in envelope.system_prompt
    assert "触发条件或动作对象" in envelope.system_prompt
    assert "独立的计划/时间窗义务" in envelope.system_prompt
    assert "参照性补充" in envelope.system_prompt
    assert "原始访视日" in envelope.system_prompt
    assert "不得扩展为原文未支持的“补访”" in envelope.system_prompt
    assert "受试者完成试验" in envelope.system_prompt
    assert "试验开始/结束判定" in envelope.system_prompt
    assert "末次访视应于第24周 D169±7d 完成" in envelope.system_prompt
    assert "委婉改写" in envelope.system_prompt
    assert "禁止重复被排除主题/家族名称" in envelope.system_prompt
    assert "不结构化安全性随访" in envelope.system_prompt
    assert "不得写负向范围免责声明" in envelope.system_prompt
    assert "uncertainty、" in envelope.system_prompt
    assert "user_action" in envelope.system_prompt
    assert "data_gap主张必须报告检索/证据/提问型不确定性" in (
        envelope.system_prompt
    )
    assert "其检索标记之前不得出现肯定性方案动作或义务" in (
        envelope.system_prompt
    )
    assert "FACT/INFERENCE/RECOMMENDATION主张保持可操作语义" in (
        envelope.system_prompt
    )


def test_v7_non_visit_protocol_prompt_has_no_visit_instructions(
    tmp_path: Path,
) -> None:
    """Visit-topic instructions stay scoped to the visit topic."""
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "48小时内复查。",
                paragraph_index=100,
            )
        ]
    )
    provider = FakeProvider([_valid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-safety-prompt",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert "访视动作家族" not in provider.envelopes[0].system_prompt


def test_v10_visit_repair_envelope_carries_topic_constraints(
    tmp_path: Path,
) -> None:
    """The single controlled repair carries the visit whitelist, forbidden
    content, splitting constraint, reschedule semantic-role rule,
    reference-complement and study-completion/end exclusions, source-
    faithfulness constraints and the excluded-family-name repetition
    prohibition alongside the validation errors."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="时间窗与补访合并条款。",
        )

    provider = FakeProvider([invalid, _valid_output])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v10-visit-repair-constraints",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    repair = provider.envelopes[1]
    assert repair.prompt_version == (
        "monitoring-protocol-clause-structuring-v12:json-repair-1"
    )
    constraints = repair.payload["protocol_evidence_constraints"]
    assert "visit_topic_constraints" in constraints
    assert "恰好一个访视动作家族" in constraints["visit_topic_constraints"]
    assert "拆分" in constraints["visit_topic_constraints"]
    assert "触发条件或动作对象" in constraints["visit_topic_constraints"]
    assert "独立的计划/时间窗义务" in constraints["visit_topic_constraints"]
    assert "参照性补充" in constraints["visit_topic_constraints"]
    assert "原始访视日" in constraints["visit_topic_constraints"]
    assert "不得把“补访”扩展进标题或正文" in constraints["visit_topic_constraints"]
    assert "完成/终止性" in constraints["visit_topic_constraints"]
    assert "改述为检索缺口" in constraints["visit_topic_constraints"]
    assert "委婉改写" in constraints["visit_topic_constraints"]
    assert "不得仅为了说明被排除主题" in constraints["visit_topic_constraints"]
    assert "不得新增负向范围免责声明" in constraints["visit_topic_constraints"]
    assert "data_gap主张必须整体呈现检索/证据/提问型不确定性" in (
        constraints["visit_topic_constraints"]
    )
    assert "其检索标记之前不得出现肯定性方案动作或义务" in (
        constraints["visit_topic_constraints"]
    )
    assert "validation_errors" in repair.payload


V8_VISIT_RESCHEDULE_CANDIDATE_TEXT = (
    "若受试者无法在研究流程图规定的访视窗口期内前往研究中心，"
    "可在另一时间重新安排访视；应尽一切努力重新安排尽可能接近原始访视日，"
    "受试者不应因排程困难而错过方案规定的访视。"
)


def test_v8_visit_exact_v7_repaired_reschedule_candidate_passes(
    tmp_path: Path,
) -> None:
    """The exact v7 repaired candidate 计划访视改期原则 is one reschedule
    rule: 计划访视 in the title and 访视窗口 in the trigger condition serve
    only the 改期/重新安排 action and must not create a schedule family."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划访视改期原则",
            text=V8_VISIT_RESCHEDULE_CANDIDATE_TEXT,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-repaired-reschedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v8_visit_adjusted_planned_visit_date_is_reschedule_only(
    tmp_path: Path,
) -> None:
    """调整计划访视日期 is one reschedule action whose object is the
    planned visit date; the embedded 计划访视/访视日期 must not create a
    schedule family."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="调整计划访视日期。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-adjusted-planned-date",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "reschedule_text",
    (
        "计划访视应重新安排。",
        "计划访视需延期。",
        "第2周访视应延期。",
        "若计划访视需进行改期，应重新安排本次访视。",
        "若无法按期到访，应在访视窗口内进行补访。",
        "若无法按期到访，应在访视窗口内完成补访。",
    ),
)
def test_v8_visit_modal_or_auxiliary_reschedule_objects_stay_reschedule_only(
    tmp_path: Path,
    reschedule_text: str,
) -> None:
    """A modal or auxiliary between a schedule term and its reschedule
    action belongs to that action; 进行/完成 governing 改期/补访 are not
    independent schedule predicates."""
    assert MonitoringAiService._visit_family_names(reschedule_text) == [
        "reschedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=reschedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-modal-reschedule-object",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "unscheduled_text",
    (
        "若无法按期到访，应在访视窗口外进行计划外访视。",
        "若无法按期到访，应在访视窗口外完成计划外访视。",
    ),
)
def test_v8_visit_window_trigger_with_unscheduled_action_is_unscheduled_only(
    tmp_path: Path,
    unscheduled_text: str,
) -> None:
    """进行/完成 directly governing 计划外访视 is not a schedule
    predicate; the window wording is only the action's trigger context."""
    assert MonitoringAiService._visit_family_names(unscheduled_text) == [
        "unscheduled"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=unscheduled_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-window-unscheduled-action",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "reschedule_text",
    (
        "若受试者无法在访视窗口期内前往研究中心，应重新安排访视。",
        "如果受试者未能按访视窗到访，可安排补访。",
        "未能按计划访视时间到访的受试者，应重新安排。",
        "若受试者无法在访视窗口内按期到访\n应重新安排访视。",
        "若受试者无法在访视窗口内按期到访；应重新安排访视。",
        "若受试者无法在访视窗口内按期到访。应重新安排访视。",
        "若所有受试者均无法在访视窗口内按期到访，应重新安排访视。",
        "若受试者均未能按计划访视时间到访，应重新安排。",
    ),
)
def test_v8_visit_trigger_window_clauses_are_reschedule_only(
    tmp_path: Path,
    reschedule_text: str,
) -> None:
    """Schedule/window wording inside 若/如果/无法/未能 trigger clauses of
    a reschedule/unscheduled action must not create a schedule family, even
    when the trigger condition and the reschedule action sit in different
    fields or punctuation segments of the operative candidate; 所有/均 are
    subject quantifiers, not schedule modals."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=reschedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-trigger-reschedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v8_visit_trigger_condition_in_one_field_governs_action_in_next(
    tmp_path: Path,
) -> None:
    """Normal structured output joins condition, time-window and
    required-action fields with newlines: a trigger condition in the
    conditions field may govern a reschedule action in the required-actions
    field, so the operative candidate as a whole stays reschedule-only."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="访视候选说明。",
            conditions=["若受试者无法在访视窗口内按期到访"],
            required_actions=["应重新安排访视。"],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-cross-field-trigger",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "reschedule_text",
    (
        "访视窗口改期原则。",
        "若无法到访，应在访视窗口内重新安排访视。",
        "在原访视窗口内重新安排访视。",
        "未能按期到访时，需调整计划访视日期至访视窗口允许范围内。",
        "计划访视补访原则。",
    ),
)
def test_v8_visit_window_as_reschedule_title_or_target_stays_reschedule_only(
    tmp_path: Path,
    reschedule_text: str,
) -> None:
    """Schedule/window wording that serves as a reschedule title or as the
    timing/target constraint of the reschedule action (在…内, 至…范围内)
    must not create a schedule family; 应/需 may govern the reschedule
    action itself and cannot by themselves prove an independent schedule
    obligation."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=reschedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v8-visit-window-target-reschedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "mixed_text",
    (
        "所有计划访视应在时间窗内完成；若无法到访，应重新安排。",
        "访视窗口为±3天；若不能按期到访，需重新安排。",
        "所有计划访视应在时间窗内完成，若无法到访应重新安排。",
        "若受试者入组，计划访视必须在时间窗内完成；若无法到访，应重新安排。",
        "若中心无法按期接诊且计划访视必须遵循原定顺序，应重新安排本次访视。",
        "若受试者不能到中心且访视计划仍应保持原定顺序，则延期本次访视。",
        "若无法到访但必须完成计划访视，则应重新安排本次访视。",
        "若不能到访但须执行计划访视，则延期本次访视。",
        "所有访视均在访视窗口内由研究者按方案要求完成；若无法到访，应重新安排。",
        "若访视窗口为±3天且无法到访，则应重新安排访视。",
        "若访视窗口规定为±3天且无法到访，应重新安排访视。",
        "第2周访视与调整计划访视日期合并条款。",
        "第2周访视与更改计划访视日期合并条款。",
        "第2周访视与修改计划访视日期合并条款。",
        "D15±3d访视与调整计划访视日期合并条款。",
    ),
)
def test_v8_visit_independent_schedule_plus_reschedule_still_rejects(
    tmp_path: Path,
    mixed_text: str,
) -> None:
    """An independent modal/predicate or quantified-visit schedule
    obligation, window definition, or week/day timing rule plus a separate
    reschedule action stays mixed and fails closed; no global reschedule
    precedence is applied."""
    assert MonitoringAiService._visit_family_names(mixed_text) == [
        "reschedule",
        "schedule",
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=mixed_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v8-visit-mixed-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message


V10_VISIT_POSTPOSITIVE_RESCHEDULE_TITLE = (
    "计划访视无法在窗口内完成时的改期/补访安排"
)


def test_v10_visit_exact_postpositive_reschedule_title_is_reschedule_only(
    tmp_path: Path,
) -> None:
    """The exact v8 canary candidate-3 title 计划访视无法在窗口内完成时
    的改期/补访安排 is reschedule-only: the schedule term precedes the
    trigger marker inside the trigger clause and only serves the
    reschedule action. A compliant rewrite of the v8 candidate-3 surface
    passes the full executable visit gate."""
    assert MonitoringAiService._visit_family_names(
        V10_VISIT_POSTPOSITIVE_RESCHEDULE_TITLE
    ) == ["reschedule"]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title=V10_VISIT_POSTPOSITIVE_RESCHEDULE_TITLE,
            text=(
                "当计划访视无法在访视窗口内完成时，研究者应安排改期或"
                "补访，并尽量贴近原定时间。"
            ),
            uncertainty="需医学经理确认改期与补访的适用情形。",
            user_action="请医学经理确认改期/补访安排是否适用于当前方案。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-postpositive-reschedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "reschedule_text",
    (
        "计划访视无法在窗口内完成时的补访安排。",
        "计划访视无法在窗口内完成时；安排改期或补访。",
        "计划访视无法在窗口内完成时，安排改期或补访。",
        "计划访视无法在窗口内完成时安排补访。",
        "计划访视不能按方案时间完成时安排改期。",
        "计划访视难以在允许范围内完成时安排补访。",
        "未能按计划访视时间到访时，安排补访。",
        "无法在窗口内完成计划访视时安排补访。",
        "计划访视无法在窗口内完成时必须改期。",
        "计划访视无法在窗口内完成时应重新安排。",
    ),
)
def test_v10_visit_postpositive_reschedule_variants_stay_reschedule_only(
    tmp_path: Path,
    reschedule_text: str,
) -> None:
    """A schedule term followed by a trigger marker (无法/不能/难以/
    未能) inside a clause that ends in a real reschedule/unscheduled
    action stays reschedule-only across punctuation forms; pre-positive
    trigger forms keep the v8 behavior; a modal placed after the trigger
    phrase governs the reschedule action (必须改期/应重新安排) and does
    not create an independent normative schedule assertion."""
    assert MonitoringAiService._visit_family_names(reschedule_text) == [
        "reschedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=reschedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-postpositive-reschedule-variants",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v10_visit_postpositive_trigger_across_fields_stays_reschedule_only(
    tmp_path: Path,
) -> None:
    """Normal structured output joins condition and required-action fields
    with newlines: the postpositive trigger condition governs the
    reschedule action in the next field, so the operative candidate stays
    reschedule-only."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="访视候选说明。",
            conditions=["计划访视无法在窗口内完成时"],
            required_actions=["安排改期或补访。"],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-cross-field-postpositive-trigger",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "schedule_text",
    (
        "计划访视无法在窗口内完成。",
        "计划访视无法在窗口内完成时受试者应到访。",
        "计划访视未能按窗口完成时，受试者应遵守访视安排。",
    ),
)
def test_v10_visit_postpositive_schedule_without_action_stays_schedule(
    tmp_path: Path,
    schedule_text: str,
) -> None:
    """Without a real reschedule/unscheduled action, the same schedule
    wording followed by a trigger marker remains schedule-only: the
    postpositive role correction never applies without an action."""
    assert MonitoringAiService._visit_family_names(schedule_text) == [
        "schedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=schedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-postpositive-schedule-only",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "mixed_text",
    (
        "第2周访视无法在窗口内完成时的改期/补访安排。",
        "D15±3d访视无法在窗口内完成时的改期安排。",
        "访视顺序无法按方案执行时的改期安排。",
        "所有计划访视均无法在窗口内完成时的改期安排。",
        "计划访视无法在访视窗口为±3天时完成时的改期安排。",
        "计划访视无法在窗口内完成时必须按原顺序执行；应改期。",
        "计划访视无法在窗口内完成时仍需完成本次计划访视；应改期。",
        "计划访视无法在窗口内完成时，访视窗口仍为±3天；应改期。",
        "计划访视无法在窗口内完成时，所有计划访视均需按期完成，"
        "无法到访者应安排补访。",
    ),
)
def test_v10_visit_postpositive_trigger_guardrails_stay_fail_closed(
    tmp_path: Path,
    mixed_text: str,
) -> None:
    """The postpositive role correction stays narrow: week/day timing,
    ordering, quantified, numeric-window and independent normative
    schedule assertions inside the clause still count as independent
    schedule content, so the candidate stays mixed and fails closed. A
    modal before its predicate (必须按原顺序执行/仍需完成本次计划访视)
    proves an independent obligation; a modal after the trigger phrase
    governing the reschedule action does not (covered in the
    reschedule-only variants test)."""
    assert MonitoringAiService._visit_family_names(mixed_text) == [
        "reschedule",
        "schedule",
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=mixed_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-postpositive-guardrails",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message


def test_v10_visit_exact_v8_negative_disclaimer_surfaces_stay_fail_closed(
    tmp_path: Path,
) -> None:
    """The exact v8 canary failure surfaces remain fail-closed: negative
    scope disclaimers naming excluded families still count lexically, and
    off-topic uncertainty/user-action wording still trips the full
    boundary gates. The corrective forbids such wording; it does not
    exempt it."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def c1_disclaimer(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划访视时间窗：双盲治疗期第2、4、8周访视",
            text=(
                "双盲治疗期第2、4、8周访视应在规定时间窗内完成；"
                "本候选不包含改期/补访、计划外访视。"
            ),
        )

    def c4_disclaimer(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划外访视：研究者可根据实际需要增加访视并记录",
            text=(
                "研究者可根据实际需要增加计划外访视并记录；"
                "本候选不结构化安全性随访。"
            ),
        )

    def c3_offtopic(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title=V10_VISIT_POSTPOSITIVE_RESCHEDULE_TITLE,
            text=("当计划访视无法在窗口内完成时安排改期或补访。"),
            uncertainty="需确认药品发放与回收环节对访视窗口的影响。",
            user_action="请医学经理确认失访受试者的改期/补访处理。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [c1_disclaimer, c1_disclaimer],
        "v10-visit-v8-c1-disclaimer-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [c4_disclaimer, c4_disclaimer],
        "v10-visit-v8-c4-disclaimer-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "safety follow-up" in job.failure_message

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [c3_offtopic, c3_offtopic],
        "v10-visit-v8-c3-offtopic-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "dispensing" in job.failure_message
    assert "withdrawal content" in job.failure_message
    assert "exactly one visit action family" not in job.failure_message


def test_v10_visit_v8_repaired_candidate_rewrites_pass(
    tmp_path: Path,
) -> None:
    """Compliant rewrites of the v8 repaired candidates 1-5 - schedule,
    schedule, reschedule, unscheduled and retrieval-gap - satisfy the
    existing executable gates when the excluded-family disclaimers and
    off-topic guidance are removed."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def c1_rewrite(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划访视时间窗：双盲治疗期第2、4、8周访视",
            text="双盲治疗期第2、4、8周访视应在规定时间窗内完成。",
        )

    def c2_rewrite(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划访视时间窗：开放治疗期第12、16、20、24周访视",
            text="开放治疗期第12、16、20、24周访视应在规定时间窗内完成。",
        )

    def c4_rewrite(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划外访视：研究者可根据实际需要增加访视并记录",
            text=(
                "研究者可根据实际需要增加计划外访视，并按方案要求记录。"
            ),
        )

    def c5_rewrite(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title=(
                "检索缺口：当前证据包未包含第1.2节试验流程表完整"
                "访视顺序与窗口表格"
            ),
            text=("需补充检索试验流程表完整访视顺序与窗口表格。"),
        )

    for builder, key in (
        (c1_rewrite, "v10-visit-v8-c1-rewrite"),
        (c2_rewrite, "v10-visit-v8-c2-rewrite"),
        (c4_rewrite, "v10-visit-v8-c4-rewrite"),
        (c5_rewrite, "v10-visit-v8-c5-rewrite"),
    ):
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [builder],
            key,
        )
        assert job.status == MonitoringAiJobStatus.COMPLETED, key


# --------------------------------------------------------------------------- #
# v10: reschedule reference complement and study completion/end boundaries
# --------------------------------------------------------------------------- #

V10_VISIT_CANARY_REFERENCE_SENTENCE = (
    "该原则适用于方案规定的访视，并应以试验流程表规定的时间窗为原始参照"
)
V10_VISIT_V9_CANDIDATE3_TEXT = (
    "如当前受试者无法在第1.2节试验流程表规定的访视窗口期内前往研究中心，"
    "可在另一时间重新安排访视。应尽一切努力重新安排尽可能接近原始访视日。"
    "受试者不应因排程困难而错过方案规定的访视。"
    "该原则适用于方案规定的访视，并应以试验流程表规定的时间窗为原始参照。"
)


def test_v10_visit_reference_complement_exact_canary_text_is_reschedule_only(
    tmp_path: Path,
) -> None:
    """The exact v9 terminal candidate-3 text now classifies reschedule-only:
    the decisive sentence 该原则适用于方案规定的访视，并应以试验流程表规定
    的时间窗为原始参照 is a reschedule reference complement carried by a real
    reschedule action, not an independent schedule obligation. The same
    sentence without any reschedule action stays schedule, so reschedule
    never gets global precedence."""
    assert MonitoringAiService._visit_family_names(
        V10_VISIT_V9_CANDIDATE3_TEXT
    ) == ["reschedule"]
    assert MonitoringAiService._visit_family_names(
        V10_VISIT_CANARY_REFERENCE_SENTENCE
    ) == ["schedule"]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="计划访视改期与补访原则",
            text=V10_VISIT_V9_CANDIDATE3_TEXT,
            subject_scope="无法在试验流程表规定窗口内到院的受试者",
            time_windows=["重新安排的访视应尽可能接近原始访视日"],
            required_actions=[
                "可在另一时间重新安排访视",
                "尽一切努力重新安排尽可能接近原始访视日",
                "避免因排程困难导致方案规定访视缺失",
            ],
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-reference-complement-canary",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "complement_text",
    (
        "无法按期到访时，可在另一时间重新安排访视，并以访视窗为参照。",
        "无法按期到访时，可在另一时间重新安排访视，以访视窗口作为依据。",
        "无法按期到访时，可重新安排访视，以研究日作为基准。",
        "无法按期到访时，可重新安排访视，以原始访视日为参照。",
        "无法按期到访时，可重新安排访视，并以访视窗为参考基准。",
    ),
)
def test_v10_visit_reference_complement_variants_stay_reschedule_only(
    tmp_path: Path,
    complement_text: str,
) -> None:
    """以/作为 + 参照|依据|基准 over time-window, study-day and visit-day
    terms stay reschedule-only when the candidate carries a real reschedule
    action."""
    assert MonitoringAiService._visit_family_names(complement_text) == [
        "reschedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=complement_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-reference-complement-variants",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "schedule_text",
    (
        "计划访视应以试验流程表规定的时间窗为参照。",
        "受试者应以原始访视日为基准安排计划访视。",
    ),
)
def test_v10_visit_reference_complement_without_action_stays_schedule(
    tmp_path: Path,
    schedule_text: str,
) -> None:
    """Without a real reschedule action the same reference wording remains
    an independent schedule assertion: the reference-complement correction
    never applies without an action."""
    assert MonitoringAiService._visit_family_names(schedule_text) == [
        "schedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=schedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-reference-complement-schedule-only",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "mixed_text",
    (
        "如受试者无法到访，可重新安排访视；访视顺序应按原始方案执行。",
        "所有计划访视均应以试验流程表规定的时间窗为参照；"
        "无法到访者可重新安排访视。",
        "访视窗口为±3天；如无法到访，可重新安排访视，并以访视窗为参照。",
        "所有计划访视均需在窗口内完成，并以原始访视日为参照；"
        "无法到访者应重新安排。",
        "无法到访时，可重新安排访视，以第2周访视为参照。",
        "无法到访时，可重新安排访视，以D15±3d访视为参照。",
        "无法到访时，可重新安排访视，以访视顺序为参照。",
        "无法到访时，可重新安排访视，以±3天访视窗口为参照。",
        "无法到访时，可重新安排访视，以3天访视窗口为参照。",
        "无法到访时，可重新安排访视，以第十二周的计划访视为参照。",
        "无法到访时，可重新安排访视，以D15的访视计划为参照。",
        "无法到访时，可重新安排访视，以72小时的访视窗口为参照。",
        "无法到访时，可重新安排访视，以3个工作日的访视窗口为参照。",
        "无法到访时，可重新安排访视，以三个工作日的访视窗口为参照。",
        "无法到访时，可重新安排访视，以七十二小时的访视窗口为参照。",
        "无法到访时，可重新安排访视，以三天访视窗口为参照。",
        "无法到访时，可重新安排访视，以十二日的访视计划为参照。",
        "无法到访时，可重新安排访视，以研究第十五日的计划访视为参照。",
        "无法到访时，可重新安排访视，以原定访视先后次序和访视安排为参照。",
        "如无法到访，可重新安排访视；须遵循原定访视先后顺序。",
    ),
)
def test_v10_visit_reference_complement_mixed_stays_fail_closed(
    tmp_path: Path,
    mixed_text: str,
) -> None:
    """The reference-complement correction stays narrow: an ordering
    obligation, a quantified obligation (even phrased with 为参照), a
    numeric-window definition, a quantified completion requirement, or a
    week/day/ordering/numeric-window term inside 以…为参照 (以第2周访视为参照,
    以D15±3d访视为参照, 以访视顺序为参照, 以±3天访视窗口为参照) plus a
    reschedule action still stays mixed and fails closed."""
    assert MonitoringAiService._visit_family_names(mixed_text) == [
        "reschedule",
        "schedule",
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=mixed_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-reference-complement-mixed-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message


def test_v10_visit_reference_complement_unscheduled_only_stays_mixed(
    tmp_path: Path,
) -> None:
    """The reference-complement exemption is authorized only for a real
    reschedule action: an unscheduled action alone plus a reference
    complement (以访视窗为参照) keeps the schedule term independent, so the
    candidate stays mixed and fails closed."""
    text = "研究者可根据安全需要增加计划外访视，并以访视窗为参照。"
    assert MonitoringAiService._visit_family_names(text) == [
        "unscheduled",
        "schedule",
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-reference-complement-unscheduled-only",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "exactly one visit action family" in job.failure_message


# The frozen v10 canary candidate-2 regression is built from exact known
# surfaces recorded in terminal evidence - the exact title, the exact three
# required actions, fact_type=visit_schedule, the presence of one fact and
# one data-gap claim, and the exact DATA_GAP sentence
# (当前证据包未检索到改期访视的量化允许范围、是否必须仍落在原访视窗内或可
# 超出原访视窗的明确规则。) - plus deterministic reconstruction for the
# surfaces the evidence does not release (subject_scope, condition, time
# window, fact claim text and the evidence id). These reconstructed parts
# are NOT a claim of exact runtime replay; the v10 failure mode they
# reproduce is the recorded one: the data-gap retrieval question counted as
# an operative schedule fact in the family gate.
V11_VISIT_CANARY_TITLE = "受试者无法在访视窗内到中心时可重新安排访视"
V11_VISIT_CANARY_ACTIONS = (
    "可在另一时间重新安排访视",
    "应尽一切努力重新安排尽可能接近原始访视日",
    "受试者不应因排程困难而错过方案规定的访视",
)
V11_VISIT_CANARY_DATA_GAP = (
    "当前证据包未检索到改期访视的量化允许范围、是否必须仍落在原访视窗内"
    "或可超出原访视窗的明确规则。"
)
V11_VISIT_CANARY_SUBJECT_SCOPE = "无法在访视窗内到中心的受试者"
V11_VISIT_CANARY_CONDITION = "受试者无法在访视窗内到中心时"
V11_VISIT_CANARY_TIME_WINDOW = "重新安排的访视应尽可能接近原始访视日"
V11_VISIT_CANARY_FACT = "受试者无法在访视窗内到中心时可重新安排访视。"


def _v11_visit_canary_output(
    envelope: AiPromptEnvelope,
    *,
    gap_text: str = V11_VISIT_CANARY_DATA_GAP,
    gap_kind: str = "data_gap",
) -> Dict[str, Any]:
    output = _valid_output(envelope)
    candidate = output["candidates"][0]
    candidate["title"] = V11_VISIT_CANARY_TITLE
    candidate["text"] = V11_VISIT_CANARY_TITLE
    candidate["structured_payload"].update(
        {
            "fact_type": "visit_schedule",
            "subject_scope": V11_VISIT_CANARY_SUBJECT_SCOPE,
            "conditions": [V11_VISIT_CANARY_CONDITION],
            "time_windows": [V11_VISIT_CANARY_TIME_WINDOW],
            "thresholds": [],
            "exceptions": [],
            "required_actions": list(V11_VISIT_CANARY_ACTIONS),
            "evidence_ids": ["evidence-1"],
        }
    )
    seed_claim = candidate["claims"][0]
    candidate["claims"] = [
        {
            **seed_claim,
            "claim_id": "claim-canary-fact",
            "kind": "fact",
            "text": V11_VISIT_CANARY_FACT,
            "evidence_ids": ["evidence-1"],
        },
        {
            **seed_claim,
            "claim_id": "claim-canary-gap",
            "kind": gap_kind,
            "text": gap_text,
            "confidence": 0.6,
            "uncertainty": "原文可能在未纳入证据包的章节或附件中。",
            "user_action": "请补充检索改期访视窗口量化规则。",
            "evidence_ids": ["evidence-1"],
        },
    ]
    return output


def _v11_visit_canary_non_gap_surfaces() -> List[str]:
    """Every operative surface of the canary shape except the data-gap
    claim: title, text, subject scope, condition, time window, the three
    required actions and the fact claim."""

    return [
        V11_VISIT_CANARY_TITLE,
        V11_VISIT_CANARY_TITLE,
        V11_VISIT_CANARY_SUBJECT_SCOPE,
        V11_VISIT_CANARY_CONDITION,
        V11_VISIT_CANARY_TIME_WINDOW,
        *list(V11_VISIT_CANARY_ACTIONS),
        V11_VISIT_CANARY_FACT,
    ]


V12_VISIT_INITIAL_REVIEW_UNCERTAINTY = (
    "当前证据包未检索到药物分发、药物回收和PK采血相关段落。"
)
V12_VISIT_PARTIAL_REPAIR_UNCERTAINTY = (
    "当前证据包未检索到药物回收相关段落。"
)
V12_VISIT_COMPLETE_REPAIR_UNCERTAINTY = (
    "当前证据包未检索到其他改期访视相关段落。"
)


def _v12_visit_canary_with_review_uncertainty(
    envelope: AiPromptEnvelope,
    uncertainty: str,
) -> Dict[str, Any]:
    output = _v11_visit_canary_output(envelope)
    candidate = output["candidates"][0]
    seed_claim = candidate["claims"][0]
    candidate["claims"].append(
        {
            **seed_claim,
            "claim_id": "claim-canary-review-gap",
            "kind": "data_gap",
            "text": "当前证据包未检索到其他改期访视证据。",
            "confidence": 0.6,
            "uncertainty": uncertainty,
            "user_action": "请补充检索原始方案相关章节。",
            "evidence_ids": ["evidence-1"],
        }
    )
    return output


def test_v12_visit_structured_diagnostics_cover_every_user_visible_surface(
    tmp_path: Path,
) -> None:
    """Every forbidden boundary hit keeps its exact output JSON path/token.

    The list order is deterministic: forbidden-family precedence, then the
    complete user-visible surface order and regex match order. Legacy
    family-level validation text remains present for compatibility.
    """
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def every_surface(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _v11_visit_canary_output(envelope)
        candidate = output["candidates"][0]
        candidate["title"] = "安全性随访安排"
        candidate["text"] = "可重新安排访视，并核对药物回收"
        candidate["structured_payload"].update(
            {
                "subject_scope": "提前退出受试者",
                "conditions": ["首次给药安排"],
                "time_windows": ["PK采血时间"],
                "thresholds": ["药物称重要求"],
                "exceptions": ["合并用药记录例外"],
                "required_actions": [
                    "完成全部研究",
                    "可在另一时间重新安排访视",
                ],
            }
        )
        candidate["claims"][0].update(
            {
                "text": "不良事件收集",
                "uncertainty": "药物分发",
                "user_action": "请安排安全随访",
            }
        )
        return output

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [every_surface, _v11_visit_canary_output],
        "v12-visit-structured-diagnostics-surfaces",
    )

    assert job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    repair_payload = provider.envelopes[1].payload
    diagnostics = repair_payload["validation_diagnostics"]
    observed = [
        (
            item["forbidden_family"],
            item["field_path"],
            item["matched_token"],
        )
        for item in diagnostics
    ]
    assert observed == [
        (
            "medication_action",
            "candidates[0].structured_payload.conditions[0]",
            "首次给药",
        ),
        (
            "dispensing_return_weighing_adherence_pk",
            "candidates[0].text",
            "回收",
        ),
        (
            "dispensing_return_weighing_adherence_pk",
            "candidates[0].structured_payload.time_windows[0]",
            "PK",
        ),
        (
            "dispensing_return_weighing_adherence_pk",
            "candidates[0].structured_payload.thresholds[0]",
            "称重",
        ),
        (
            "dispensing_return_weighing_adherence_pk",
            "candidates[0].claims[0].uncertainty",
            "分发",
        ),
        (
            "early_or_consent_withdrawal",
            "candidates[0].structured_payload.subject_scope",
            "提前退出",
        ),
        (
            "safety_follow_up",
            "candidates[0].title",
            "安全性随访",
        ),
        (
            "safety_follow_up",
            "candidates[0].claims[0].user_action",
            "安全随访",
        ),
        (
            "ae_or_cm_collection",
            "candidates[0].structured_payload.exceptions[0]",
            "合并用药记录",
        ),
        (
            "ae_or_cm_collection",
            "candidates[0].claims[0].text",
            "不良事件收集",
        ),
        (
            "subject_or_study_completion",
            "candidates[0].structured_payload.required_actions[0]",
            "完成全部研究",
        ),
    ]
    assert all(item["candidate_index"] == 0 for item in diagnostics)
    assert all(item["candidate_number"] == 1 for item in diagnostics)
    assert all(
        item["code"] == "visit_topic_forbidden_family"
        for item in diagnostics
    )
    assert all(
        item["repair_action"] == "regenerate_entire_user_visible_field"
        for item in diagnostics
    )
    validation_errors = repair_payload["validation_errors"]
    assert "study-treatment or concomitant-medication actions" in (
        validation_errors
    )
    assert "dispensing, return, weighing, adherence or PK" in (
        validation_errors
    )
    assert "early or consent withdrawal" in validation_errors
    assert "safety follow-up" in validation_errors
    assert "AE or CM collection" in validation_errors
    assert "subject completion, study completion/end" in validation_errors
    repair_contract = repair_payload["repair_contract"]
    assert repair_contract["diagnostic_schema_version"] == (
        "monitoring_visit_topic_boundary_diagnostics_v1"
    )
    assert repair_contract["regenerate_complete_affected_fields"] is True
    assert repair_contract["forbid_token_only_deletion"] is True
    assert repair_contract["forbid_post_generation_mutation"] is True
    assert repair_contract["affected_field_paths"] == list(
        dict.fromkeys(item["field_path"] for item in diagnostics)
    )


@pytest.mark.parametrize(
    ("repair_uncertainty", "residual_tokens"),
    (
        (
            V12_VISIT_INITIAL_REVIEW_UNCERTAINTY,
            ["分发", "回收", "PK"],
        ),
        (
            V12_VISIT_PARTIAL_REPAIR_UNCERTAINTY,
            ["回收"],
        ),
    ),
)
def test_v12_visit_unchanged_or_partial_repair_is_terminal_with_residual_path(
    tmp_path: Path,
    repair_uncertainty: str,
    residual_tokens: List[str],
) -> None:
    """Unchanged and partial repairs remain fail-closed after one attempt."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def initial(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v12_visit_canary_with_review_uncertainty(
            envelope,
            V12_VISIT_INITIAL_REVIEW_UNCERTAINTY,
        )

    def incomplete_repair(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v12_visit_canary_with_review_uncertainty(
            envelope,
            repair_uncertainty,
        )

    provider = FakeProvider([initial, incomplete_repair])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key=(
            "v12-visit-residual-"
            + "-".join(residual_tokens).casefold()
        ),
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert result.job.retryable is False
    assert len(provider.envelopes) == 2
    assert service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    ) == ()
    initial_diagnostics = provider.envelopes[1].payload[
        "validation_diagnostics"
    ]
    assert [item["matched_token"] for item in initial_diagnostics] == [
        "分发",
        "回收",
        "PK",
    ]
    assert {
        item["field_path"] for item in initial_diagnostics
    } == {"candidates[0].claims[2].uncertainty"}
    repair_contract = provider.envelopes[1].payload["repair_contract"]
    assert repair_contract["affected_field_paths"] == [
        "candidates[0].claims[2].uncertainty"
    ]
    assert "重新生成整个用户可见字段" in repair_contract["instruction"]
    assert "不得只删除matched_token" in repair_contract["instruction"]
    assert (
        "visit protocol candidates cannot contain dispensing"
        in provider.envelopes[1].payload["validation_errors"]
    )
    attempt = service.repository.attempts(
        "project-alpha",
        result.job.job_id,
    )[0]
    residual = attempt["response"]["validation_diagnostics"]
    assert [item["matched_token"] for item in residual] == residual_tokens
    assert {
        item["field_path"] for item in residual
    } == {"candidates[0].claims[2].uncertainty"}
    assert "candidates[0].claims[2].uncertainty" in (
        result.job.failure_message
    )
    for token in residual_tokens:
        assert token in result.job.failure_message


def test_v12_visit_complete_field_repair_passes_after_structured_diagnostics(
    tmp_path: Path,
) -> None:
    """A complete regeneration removes every forbidden hit and can pass."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def initial(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v12_visit_canary_with_review_uncertainty(
            envelope,
            V12_VISIT_INITIAL_REVIEW_UNCERTAINTY,
        )

    def complete_repair(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v12_visit_canary_with_review_uncertainty(
            envelope,
            V12_VISIT_COMPLETE_REPAIR_UNCERTAINTY,
        )

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [initial, complete_repair],
        "v12-visit-complete-field-regeneration",
    )

    assert job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    diagnostics = provider.envelopes[1].payload["validation_diagnostics"]
    assert [item["matched_token"] for item in diagnostics] == [
        "分发",
        "回收",
        "PK",
    ]
    assert {
        item["field_path"] for item in diagnostics
    } == {"candidates[0].claims[2].uncertainty"}


def test_v11_visit_exact_v10_canary_surfaces_plus_reconstruction_pass(
    tmp_path: Path,
) -> None:
    """The frozen v10 canary candidate-2 shape (exact known surfaces plus
    deterministic reconstruction) now completes initial validation as
    reschedule only and never enters repair: the exact retrieval-framed
    DATA_GAP sentence (当前证据包未检索到改期访视的量化允许范围、是否必须
    仍落在原访视窗内或可超出原访视窗的明确规则。) is review guidance about
    missing evidence and cannot create a schedule family, while every
    other operative surface together classifies as exactly one reschedule
    family. The data-gap claim text remains fully bound to evidence and
    stays in the boundary view."""
    assert (
        monitoring_ai_service_module.MonitoringAiService._visit_family_names(
            "\n".join(_v11_visit_canary_non_gap_surfaces())
        )
        == ["reschedule"]
    )
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def canary(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v11_visit_canary_output(envelope)

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [canary],
        "v11-canary-reschedule-only",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED
    # Initial validation passed: exactly one provider call, no repair.
    assert len(provider.envelopes) == 1
    persisted = _service(tmp_path, provider).repository.candidates(
        "project-alpha",
        job.job_id,
    )
    assert len(persisted) == 1
    assert persisted[0].claims[1].text == V11_VISIT_CANARY_DATA_GAP


def test_v11_visit_canary_gap_text_as_fact_inference_recommendation_fails(
    tmp_path: Path,
) -> None:
    """The same mixed-family gap text declared as FACT, INFERENCE or
    RECOMMENDATION stays operative and remains fail-closed: only the
    DATA_GAP kind is excluded when retrieval-framed, so changing the claim
    kind cannot smuggle the schedule assertion past the one-family gate.
    The aggregate error carries the detected families and a deterministic
    family trace (surface path, claim kind, matched span), and the trace is
    carried into the controlled-repair validation-errors payload."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    for kind in ("fact", "inference", "recommendation"):
        def disguised(envelope: AiPromptEnvelope) -> Dict[str, Any]:
            return _v11_visit_canary_output(
                envelope,
                gap_text=V11_VISIT_CANARY_DATA_GAP,
                gap_kind=kind,
            )

        job, provider = _run_visit_builder(
            tmp_path,
            payload,
            [disguised, disguised],
            f"v11-canary-kind-{kind}",
        )
        assert job.status == MonitoringAiJobStatus.FAILED
        assert job.failure_code == "invalid_ai_output"
        assert "exactly one visit action family" in job.failure_message
        assert "detected families: reschedule, schedule" in (
            job.failure_message
        )
        assert (
            f"claims[1].text (kind={kind})" in job.failure_message
        )
        assert "schedule <- claims[1].text (kind=" in job.failure_message
        assert "family trace:" in job.failure_message
        # Terminal after exactly one controlled repair; the trace travels in
        # the repair validation-errors payload.
        assert len(provider.envelopes) == 2
        repair_errors = provider.envelopes[1].payload["validation_errors"]
        assert "detected families: reschedule, schedule" in repair_errors
        assert f"claims[1].text (kind={kind})" in repair_errors
        assert "family trace:" in repair_errors


def test_v11_visit_affirmative_data_gap_disguise_fails_kind_semantics_gate(
    tmp_path: Path,
) -> None:
    """A DATA_GAP claim that affirmatively states a protocol obligation
    (所有计划访视均应在时间窗内完成) without retrieval framing stays in
    the operative family view and fails the fail-closed kind-semantics
    gate: changing claim kind cannot bypass family validation. The gate
    error names the claim surface and kind, and the one-family error still
    fires with the family trace."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def disguised(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v11_visit_canary_output(
            envelope,
            gap_text="所有计划访视均应在时间窗内完成",
            gap_kind="data_gap",
        )

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [disguised, disguised],
        "v11-canary-data-gap-disguise",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in job.failure_message
    )
    assert (
        "cannot bypass family validation by changing claim kind"
        in job.failure_message
    )
    assert "claims[1].text (kind=data_gap)" in job.failure_message
    assert "exactly one visit action family" in job.failure_message
    assert "detected families: reschedule, schedule" in (
        job.failure_message
    )
    assert len(provider.envelopes) == 2
    repair_errors = provider.envelopes[1].payload["validation_errors"]
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in repair_errors
    )


@pytest.mark.parametrize(
    "gap_text",
    (
        "所有计划访视均应在时间窗内完成，当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成；当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，但当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，然而当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，同时当前证据包未检索到量化依据",
    ),
)
def test_v11_visit_mixed_affirmative_plus_gap_fails_kind_semantics(
    tmp_path: Path,
    gap_text: str,
) -> None:
    """A leading affirmative visit obligation cannot be laundered by a
    trailing retrieval marker: the DATA_GAP kind-semantics gate splits at
    sentence/semicolon/newline and adversative/additive boundaries
    (但/然而/同时), so every family-bearing clause must itself be under
    retrieval framing. The mixed shapes stay fail-closed with the
    kind-semantics error and the one-family error."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def mixed(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v11_visit_canary_output(
            envelope,
            gap_text=gap_text,
            gap_kind="data_gap",
        )

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [mixed, mixed],
        "v11-canary-mixed-bypass",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in job.failure_message
    )
    assert "claims[1].text (kind=data_gap)" in job.failure_message
    assert "exactly one visit action family" in job.failure_message
    assert "detected families: reschedule, schedule" in (
        job.failure_message
    )
    assert len(provider.envelopes) == 2
    repair_errors = provider.envelopes[1].payload["validation_errors"]
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in repair_errors
    )


def test_v11_data_gap_retrieval_scope_dominance_matrix() -> None:
    """Retrieval-scope dominance over family spans: a retrieval/question/
    uncertainty marker governs family-bearing text only at or after that
    marker within strong boundaries (。；！？/newline) and adversative
    connectors (但/然而/同时); a later marker never retroactively washes an
    earlier affirmative family assertion, and a retrieval scope established
    before the first family span propagates forward across coordination
    (且/并/、)."""
    fail_cases = (
        "所有计划访视均应在时间窗内完成，当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成；当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，但当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，然而当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成，同时当前证据包未检索到量化依据",
        "所有计划访视均应在时间窗内完成。当前证据包未检索到量化依据",
        "应重新安排访视，当前证据包未检索到改期依据",
    )
    pass_cases = (
        "当前证据包未检索到改期访视是否必须仍落在原访视窗内，并可超出原访视窗的适用条件。",
        "当前证据包未检索到改期访视的量化允许范围、是否必须仍落在原访视窗内或可超出原访视窗的明确规则。",
        "方案是否规定受试者无法在访视窗内到中心时可重新安排访视？",
        "当前证据包未检索到受试者首次给药的原文规定。",
    )
    for text in fail_cases:
        assert monitoring_ai_service_module.MonitoringAiService._visit_data_gap_is_retrieval(
            text
        ) is False, text
    for text in pass_cases:
        assert monitoring_ai_service_module.MonitoringAiService._visit_data_gap_is_retrieval(
            text
        ) is True, text


def test_v11_visit_same_family_data_gap_disguise_always_fails(
    tmp_path: Path,
) -> None:
    """A DATA_GAP claim that affirmatively states a protocol action always
    fails the kind-semantics gate even when it adds no new family relative
    to the rest of the candidate: the reschedule disguise on an already
    reschedule-only candidate still fails, and the one-family gate alone
    would not have caught it."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def disguised(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v11_visit_canary_output(
            envelope,
            gap_text="可在另一时间重新安排访视",
            gap_kind="data_gap",
        )

    job, provider = _run_visit_builder(
        tmp_path,
        payload,
        [disguised, disguised],
        "v11-canary-same-family-disguise",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in job.failure_message
    )
    assert (
        "cannot bypass family validation by changing claim kind"
        in job.failure_message
    )
    assert "claims[1].text (kind=data_gap)" in job.failure_message
    # The operative family view stays reschedule-only: the failure is the
    # kind-semantics gate alone, not the one-family gate.
    assert "exactly one visit action family" not in job.failure_message
    assert len(provider.envelopes) == 2
    repair_errors = provider.envelopes[1].payload["validation_errors"]
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        in repair_errors
    )


def test_v11_multi_candidate_long_diagnostics_keep_all_markers_and_locators(
    tmp_path: Path,
) -> None:
    """Five legal maximum-length titles plus long diagnostics fit below the
    global controlled-error bound with every full marker and locator."""
    titles = {
        index: (
            f"长输出候选 {index}"
            + "题" * (500 - len(f"长输出候选 {index}"))
        )
        for index in range(1, 6)
    }
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def long_failing(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidates = []
        for index in range(1, 6):
            seed = output["candidates"][0]["claims"][0]
            candidates.append(
                {
                    "candidate_type": "protocol_clause_structure",
                    "title": titles[index],
                    "text": "所有计划访视均应在时间窗内完成",
                    "structured_payload": {
                        "clause_id": f"clause-long-{index}",
                        "fact_type": "visit_schedule",
                        "subject_scope": "所有已随机受试者",
                        "conditions": [],
                        "time_windows": [],
                        "thresholds": [],
                        "exceptions": [],
                        "required_actions": [
                            "受试者首次给药安排",
                            "研究药物发放与回收",
                            "提前退出处理",
                            "安全性随访安排",
                            "记录AE和合并用药情况",
                            "完成全部计划访视后视为完成试验",
                            "可在另一时间重新安排访视",
                        ],
                        "evidence_ids": ["evidence-1"],
                    },
                    "claims": [
                        {
                            **seed,
                            "claim_id": f"claim-long-{index}",
                            "text": f"候选 {index} 需要医学复核。",
                            "evidence_ids": ["evidence-1"],
                        },
                        {
                            **seed,
                            "claim_id": f"claim-long-gap-{index}",
                            "kind": "data_gap",
                            "text": "所有计划访视均应在时间窗内完成",
                            "confidence": 0.6,
                            "uncertainty": "原文可能在未纳入证据包的章节中。",
                            "user_action": "请补充检索。",
                            "evidence_ids": ["evidence-1"],
                        },
                    ],
                }
            )
        output["candidates"] = candidates
        return output

    provider = FakeProvider([long_failing, long_failing])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v11-multi-candidate-long",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert len(provider.envelopes) == 2
    repair_errors = provider.envelopes[1].payload["validation_errors"]
    assert len(repair_errors) <= 4_000
    for index in range(1, 6):
        assert f"candidate {index} ({titles[index]}):" in repair_errors
    for index in range(1, 6):
        block_start = repair_errors.index(
            f"candidate {index} ({titles[index]}):"
        )
        block_end = repair_errors.find(
            "\ncandidate ",
            block_start + len(f"candidate {index} ({titles[index]}):"),
        )
        if block_end == -1:
            block_end = len(repair_errors)
        block = repair_errors[block_start:block_end]
        assert "family trace:" in block
        assert " <- " in block
    assert service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    ) == ()


def test_v11_candidate_detail_requires_complete_locator_not_trace_label() -> None:
    """A trace label before the cut does not count when its locator is after
    the cut; the compact complete locator is re-appended."""
    errors = [
        "x" * 620,
        (
            "visit protocol candidate must contain exactly one visit action "
            "family; detected families: reschedule, schedule; family trace: "
            + "padding" * 30
            + "; schedule <- time_windows[0] span '访视窗口'"
        ),
    ]
    bounded = (
        monitoring_ai_service_module.MonitoringAiService
        ._bounded_candidate_detail(errors, limit=700)
    )
    assert len(bounded) <= 700
    assert "family trace: schedule <- time_windows[0] span '访视窗口'" in bounded


@pytest.mark.parametrize("extra", [1, 2, 3])
def test_v11_candidate_detail_locator_plus_small_remainder_is_bounded(
    extra: int,
) -> None:
    """A 1-3 character remainder cannot trigger Python negative slicing."""
    errors = [
        "x" * 620,
        (
            "visit protocol candidate must contain exactly one visit action "
            "family; family trace: schedule <- title span '访视窗口'"
        ),
    ]
    locator = (
        monitoring_ai_service_module.MonitoringAiService
        ._family_locator_snippet(errors)
    )
    assert locator is not None
    limit = len(locator) + extra
    bounded = (
        monitoring_ai_service_module.MonitoringAiService
        ._bounded_candidate_detail(errors, limit=limit)
    )
    assert bounded == locator
    assert len(bounded) <= limit


def test_v11_candidate_aggregate_near_saturated_budget_keeps_all_locators() -> None:
    """A three-character aggregate remainder stays bounded and preserves all
    five maximum-title markers and their complete minimum locators."""
    service_type = monitoring_ai_service_module.MonitoringAiService
    titles = ["题" * 500 for _index in range(5)]
    errors = [
        ["prefix " * 100 + f"; family trace: schedule <- title span '{index}'"]
        for index in range(5)
    ]
    markers = [
        f"candidate {index} ({titles[index - 1]}): "
        for index in range(1, 6)
    ]
    minimums = [
        service_type._family_locator_snippet(item) for item in errors
    ]
    assert all(minimum is not None for minimum in minimums)
    budget = (
        monitoring_ai_service_module._CONTROLLED_VALIDATION_ERROR_LIMIT
        - len("protocol candidate validation failed:\n")
        - len("MonitoringAiOutputValidationError: ")
    )
    mandatory = (
        sum(len(marker) for marker in markers)
        + sum(len(minimum or "") for minimum in minimums)
        + 4
    )
    pad = budget - mandatory - 3
    assert pad > 0
    errors[-1][0] = (
        "prefix " * 100
        + "; family trace: schedule <- title span '"
        + "位" * (pad + 1)
        + "'"
    )
    candidate_errors = [
        (index, titles[index - 1], errors[index - 1])
        for index in range(1, 6)
    ]
    detail = service_type._bounded_protocol_candidate_errors(candidate_errors)
    controlled = (
        "MonitoringAiOutputValidationError: "
        "protocol candidate validation failed:\n"
        + detail
    )
    assert len(controlled) <= 4_000
    for index, title, item_errors in candidate_errors:
        assert f"candidate {index} ({title}): " in detail
        locator = service_type._family_locator_snippet(item_errors)
        assert locator is not None
        assert locator in detail


def test_v11_visit_framed_data_gap_stays_in_boundary_gates(
    tmp_path: Path,
) -> None:
    """Retrieval-framed DATA_GAP claim text is excluded only from visit
    action-family counting; it stays in the full boundary view, so
    medication content inside a framed gap claim still fails the
    medication gate and never reaches the one-family classifier."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def gap_medication(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _v11_visit_canary_output(
            envelope,
            gap_text="当前证据包未检索到受试者首次给药的原文规定。",
            gap_kind="data_gap",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [gap_medication, gap_medication],
        "v11-canary-gap-boundary-retained",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "study-treatment or concomitant-medication actions"
        in job.failure_message
    )
    assert "exactly one visit action family" not in job.failure_message
    assert (
        "visit DATA_GAP claim kind requires retrieval-gap framing"
        not in job.failure_message
    )


def test_v10_visit_makeup_visit_without_source_support_fails(
    tmp_path: Path,
) -> None:
    """The exact makeup-visit action term 补访 fails deterministically when
    none of the candidate's bound evidence quotes directly supports it: the
    source only says 重新安排, so the expansion is rejected even though the
    family classification is reschedule-only."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "受试者无法按期到访时，可在另一时间重新安排访视。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="漏访受试者可在另一时间安排补访。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-makeup-visit-unsupported",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "visit protocol candidate uses 补访 without a bound evidence "
        "quote that directly supports the makeup-visit term"
        in job.failure_message
    )
    assert "exactly one visit action family" not in job.failure_message


def test_v10_visit_makeup_visit_with_source_support_passes(
    tmp_path: Path,
) -> None:
    """With a bound evidence quote that directly contains 补访, the same
    makeup-visit candidate is reschedule-only and completes."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "漏访受试者可在另一时间安排补访。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="漏访受试者可在另一时间安排补访。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-makeup-visit-supported",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v10_visit_makeup_visit_conflict_only_evidence_does_not_support(
    tmp_path: Path,
) -> None:
    """Conflict-only evidence can never authorize the affirmative 补访: the
    only quote containing 补访 belongs to a declared source conflict (also
    expanded into evidence_ids), so the direct-support set excludes it and
    the candidate still fails the makeup-visit source gate deterministically."""
    conflict = {
        "conflict_id": "conflict-makeup-1",
        "action": "reschedule_principle",
        "modalities": ["required", "optional"],
        "status": "requires_user_resolution",
        "evidence_ids": ["evidence-c", "evidence-c2"],
    }
    payload = _protocol_v2_payload(
        [
            _paragraph(
                "evidence-1",
                "受试者无法按期到访时，可在另一时间重新安排访视。",
                paragraph_index=100,
            ),
            _paragraph(
                "evidence-c",
                "漏访受试者可在另一时间安排补访。",
                paragraph_index=101,
            ),
            _paragraph(
                "evidence-c2",
                "改期后的访视应尽可能接近原始访视日。",
                paragraph_index=102,
            ),
        ],
        topic_id="visit_window_and_order",
        conflicts=(conflict,),
    )
    payload["context"]["candidate_fact_types"] = [
        "visit_schedule",
        "visit_window",
    ]

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate["title"] = "漏访补访安排"
        candidate["text"] = "漏访受试者可在另一时间安排补访。"
        candidate["structured_payload"].update(
            {
                "subject_scope": "所有已随机受试者",
                "conditions": [],
                "time_windows": [],
                "thresholds": [],
                "exceptions": [],
                "required_actions": [],
                "evidence_ids": [
                    "evidence-1",
                    "evidence-c",
                    "evidence-c2",
                ],
                "source_conflicts": [dict(conflict)],
            }
        )
        seed_claim = candidate["claims"][0]
        candidate["claims"] = [
            {
                **seed_claim,
                "claim_id": "claim-makeup-conflict",
                "text": "漏访受试者可在另一时间安排补访。",
                "evidence_ids": [
                    "evidence-1",
                    "evidence-c",
                    "evidence-c2",
                ],
            },
            {
                **seed_claim,
                "claim_id": "claim-makeup-conflict-note",
                "kind": "data_gap",
                "text": "两处原文对改期/补访表述不一致，需用户裁决。",
                "confidence": 0.6,
                "uncertainty": "一处仅表述重新安排，另一处表述补访。",
                "user_action": "请医学经理裁决两处原文的适用关系。",
                "evidence_ids": ["evidence-c", "evidence-c2"],
            },
        ]
        return output

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-makeup-visit-conflict-only",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "visit protocol candidate uses 补访 without a bound evidence "
        "quote that directly supports the makeup-visit term"
        in job.failure_message
    )


V10_VISIT_FINAL_VISIT_SCHEDULE = "末次访视应于第24周 D169±7d 完成"


@pytest.mark.parametrize(
    "field,payload_text",
    (
        (
            "text",
            "个体受试者完成本临床研究方案计划的末次访视或试验流程后，"
            "视为该例受试者完成试验。",
        ),
        (
            "text",
            "最后一例受试者完成方案计划的末次访视或试验流程后，"
            "视为整个试验结束。",
        ),
        ("text", "总体试验从首例受试者签署知情同意书开始。"),
        ("text", "研究结束时点定义为最后一例受试者完成末次访视。"),
        ("text", "研究结束时间为最后一例受试者完成末次访视的日期。"),
        ("title", "计划访视完成与试验结束判定"),
        ("subject_scope", "全体受试者用于个体完成与试验结束判定"),
        (
            "required_actions",
            "个体受试者完成末次访视或试验流程后视为该例受试者完成试验",
        ),
        ("uncertainty", "视为受试者完成试验或研究结束的判定依据缺失。"),
        ("user_action", "请确认该例受试者完成试验的判定路径。"),
    ),
)
def test_v10_visit_rejects_study_completion_end_and_start_determination(
    tmp_path: Path,
    field: str,
    payload_text: str,
) -> None:
    """Subject completion, study completion/end and study start/end
    determination facts fail the visit topic boundary even when they only
    appear through a title, subject scope, required action, uncertainty or
    user-action mention of a final/planned visit."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "text": "计划访视应在允许时间窗内完成。",
            "time_windows": ["访视窗内"],
        }
        if field == "required_actions":
            kwargs[field] = [payload_text]
        else:
            kwargs[field] = payload_text
        return _visit_output(envelope, **kwargs)

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v10-visit-completion-end-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "subject completion, study completion/end or study start/end "
        "determination content" in job.failure_message
    )


def test_v10_visit_final_visit_schedule_stays_schedule(
    tmp_path: Path,
) -> None:
    """A genuine final-visit schedule such as 末次访视应于第24周 D169±7d
    完成 remains schedule content: the completion/end boundary rejects
    study-level facts, not the visit itself."""
    assert MonitoringAiService._visit_family_names(
        V10_VISIT_FINAL_VISIT_SCHEDULE
    ) == ["schedule"]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=V10_VISIT_FINAL_VISIT_SCHEDULE,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-final-visit-schedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "schedule_text",
    (
        "末次访视应在研究结束前7天内完成",
        "研究结束访视应于第24周完成",
        "试验结束访视应在D169±7d完成",
        "研究终止访视应于第24周完成",
        "试验终止访视应在D169±7d完成",
        "研究结束时应完成末次访视",
        "末次访视应在研究结束时间前7天内完成",
        "研究结束时间后7天内完成末次访视",
        "研究结束时点后7天内完成末次访视",
        "该次评估视为研究结束访视，应在第24周完成",
    ),
)
def test_v10_visit_study_end_anchored_schedules_pass(
    tmp_path: Path,
    schedule_text: str,
) -> None:
    """Study end as a visit name (研究结束访视/试验结束访视) or as a
    temporal anchor (研究结束前/时) does not make a true visit schedule a
    completion/end determination: these stay schedule and pass, while
    actual determinations such as 视为该例受试者完成试验/视为整个试验结束
    remain rejected."""
    assert MonitoringAiService._visit_family_names(schedule_text) == [
        "schedule"
    ]
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "末次访视应在研究结束前完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=schedule_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v10-visit-study-end-anchored-schedule",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


# --------------------------------------------------------------------------- #
# v10: exact five-candidate v9 repair-output replay
# --------------------------------------------------------------------------- #

V10_VISIT_V9_REPLAY_EVIDENCE = (
    (
        "e-week-db",
        "第2W（D15±3d）、4W（D29±3d）、8W（D57±3d）在研究中心用药前，"
        "进行IGA、BSA、EASI、SCORAD、DLQI（CDLQI）评估。",
    ),
    (
        "e-week-ol-preg",
        "仅限具有生育能力的女性。第12W（D85±7d）、16W（D113±7d）、"
        "20W（D141±7d）在研究中心用药前进行血（尿）清妊娠试验，"
        "第24周访视时需进行血清妊娠试验。",
    ),
    (
        "e-week-ol-days",
        "第12W（D85±7d）、16W（D113±7d）、20W（D141±7d）将回收前一次"
        "访视分发的研究药物和日记卡，并分发下一个访视周期的研究药物和"
        "日记卡。第24W（D169±7d）将仅回收已分发的研究药物和日记卡，"
        "不再进行分发。",
    ),
    (
        "e-visit-schedule-ref",
        "试验访视时间表见第1.2节试验流程表。",
    ),
    (
        "e-all-windows",
        "所有访视均应在第1.2节试验流程表中规定的时间窗内进行。应尽一切"
        "努力让每名受试者按计划参加每次访视。但是，如果受试者无法在研究"
        "流程图规定的访视窗口期内前往研究中心，则可在另一时间重新安排"
        "访视。应尽一切努力重新安排尽可能接近原始访视日。受试者不应因"
        "排程困难而错过方案规定的访视。",
    ),
    (
        "e-reschedule-dispense",
        "应按照第1.2节试验流程表中规定的访视窗内分发和回收研究药物。如果"
        "受试者无法在试验流程表规定的访视窗内前往研究中心，可在另一时间"
        "重新安排访视。应尽一切努力重新安排尽可能接近原始访视日。受试者"
        "不应因排程困难而错过方案规定的访视。",
    ),
    ("e-unscheduled-title", "计划外访视"),
    (
        "e-unscheduled",
        "出于对受试者安全的考虑，研究者可根据实际需要增加对受试者的访视"
        "次数，即计划外访视。研究者应在研究文件中对受试者的每次计划外"
        "访视内容进行记录。",
    ),
    (
        "e-completion-end",
        "总体试验从首例受试者签署知情同意书开始。个体受试者完成本临床"
        "研究方案计划的末次访视或试验流程后，视为该例受试者完成试验。"
        "最后一例受试者完成本临床研究方案计划的末次访视或试验流程后，"
        "视为整个试验结束。",
    ),
)


def _v9_replay_candidates(
    seed_output: Dict[str, Any],
    *,
    cleaned: bool,
) -> List[Dict[str, Any]]:
    """Exact five candidates of the v9 terminal repaired provider output
    (evidence ids remapped to the replay packet). ``cleaned`` swaps the
    candidate-3 title to the source-faithful wording (the source only ever
    says 重新安排, never 补访) and replaces the completion/end candidate 5
    with a genuine retrieval-gap candidate, per the v10 prompt contract."""
    seed_claim = seed_output["candidates"][0]["claims"][0]

    def candidate(
        title: str,
        text: str,
        structured_payload: Dict[str, Any],
        claims: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "candidate_type": "protocol_clause_structure",
            "title": title,
            "text": text,
            "structured_payload": structured_payload,
            "claims": [
                {
                    **seed_claim,
                    **claim,
                }
                for claim in claims
            ],
        }

    reschedule_title = (
        "计划访视改期原则" if cleaned else "计划访视改期与补访原则"
    )
    # The cleaned bundle keeps only directly source-supported content: the
    # unsupported transition/scope and skin-lesion/treatment-context
    # inferences and the repeated-context duplicate inference are dropped,
    # and the reschedule candidate keeps only the source-faithful rule with
    # the exact 原始访视日 constraint (no invented 为原始参照 sentence).
    def operative_claims(
        claims: Sequence[Dict[str, Any]],
    ) -> Sequence[Dict[str, Any]]:
        return claims if not cleaned else claims[:1]

    reschedule_text = (
        "如当前受试者无法在第1.2节试验流程表规定的访视窗口期内前往研究"
        "中心，可在另一时间重新安排访视。应尽一切努力重新安排尽可能接近"
        "原始访视日。受试者不应因排程困难而错过方案规定的访视。"
        if cleaned
        else V10_VISIT_V9_CANDIDATE3_TEXT
    )
    # The cleaned open-label candidate drops the 开放治疗期 phase premise
    # from every user-visible and structured field: the replay packet has no
    # direct evidence for that scope, so only the week-24 visit window facts
    # stay.
    open_label_title = (
        "计划访视时间窗：第12、16、20、24周访视"
        if cleaned
        else "计划访视时间窗：开放治疗期第12、16、20、24周访视"
    )
    open_label_text = (
        "当前受试者应按第1.2节试验流程表进行第12周、第16周、第20周和第24周"
        "计划访视；对应访视日分别为D85±7天、D113±7天、D141±7天和D169±7天。"
        "所有访视均应在试验流程表规定的时间窗内进行，并应尽一切努力让每名"
        "受试者按计划参加每次访视。"
        if cleaned
        else (
            "当前受试者在开放治疗期应按第1.2节试验流程表进行第12周、第16周、"
            "第20周和第24周计划访视；对应访视日分别为D85±7天、D113±7天、"
            "D141±7天和D169±7天。所有访视均应在试验流程表规定的时间窗内"
            "进行，并应尽一切努力让每名受试者按计划参加每次访视。"
        )
    )
    open_label_scope = (
        "按第1.2节试验流程表进行第12至24周计划访视的受试者"
        if cleaned
        else "进入开放治疗期的受试者"
    )
    open_label_conditions = (
        ["访视为方案规定的第12周、第16周、第20周或第24周访视"]
        if cleaned
        else [
            "受试者处于开放治疗期",
            "访视为方案规定的第12周、第16周、第20周或第24周访视",
        ]
    )
    open_label_fact_text = (
        "第12、16、20、24周访视分别对应D85±7天、D113±7天、D141±7天和"
        "D169±7天，且所有访视应在试验流程表规定的时间窗内进行。"
        if cleaned
        else (
            "开放治疗期第12、16、20、24周访视分别对应D85±7天、"
            "D113±7天、D141±7天和D169±7天，且所有访视应在试验流程表"
            "规定的时间窗内进行。"
        )
    )
    completion_end_candidate = (
        candidate(
            "第1.2节试验流程表逐行访视清单：检索缺口",
            "第1.2节试验流程表规定的计划访视逐行时间窗与程序清单未在"
            "当前证据包中展开。",
            {
                "clause_id": "visit_schedule_table_gap",
                "fact_type": "visit_schedule",
                "subject_scope": "计划访视时间窗核对的医学经理",
                "conditions": [],
                "time_windows": [],
                "thresholds": [],
                "exceptions": [],
                "required_actions": [],
                "evidence_ids": ["e-visit-schedule-ref"],
                "source_conflicts": [],
            },
            [
                {
                    "claim_id": "clm_schedule_table_gap",
                    "kind": "data_gap",
                    "text": "当前证据包未检索到第1.2节试验流程表逐行访视名称"
                    "与程序清单。",
                    "confidence": 0.6,
                    "uncertainty": "原文可能在未纳入证据包的章节或附件中。",
                    "user_action": "请补充检索第1.2节试验流程表逐行内容。",
                    "evidence_ids": ["e-visit-schedule-ref"],
                }
            ],
        )
        if cleaned
        else candidate(
            "计划访视完成与试验结束判定",
            "个体受试者完成本临床研究方案计划的末次访视或试验流程后，"
            "视为该例受试者完成试验；最后一例受试者完成方案计划的末次"
            "访视或试验流程后，视为整个试验结束。",
            {
                "clause_id": "visit_completion_and_study_end",
                "fact_type": "visit_schedule",
                "subject_scope": "全体受试者用于个体完成与试验结束判定",
                "conditions": [
                    "个体受试者完成方案计划的末次访视或试验流程",
                    "最后一例受试者完成方案计划的末次访视或试验流程",
                ],
                "time_windows": [],
                "thresholds": [],
                "exceptions": [],
                "required_actions": [
                    "个体受试者完成末次访视或试验流程后视为该例受试者完成试验",
                    "最后一例受试者完成末次访视或试验流程后视为整个试验结束",
                ],
                "evidence_ids": ["e-completion-end"],
                "source_conflicts": [],
            },
            [
                {
                    "claim_id": "clm_completion_fact",
                    "kind": "fact",
                    "text": "个体受试者完成方案计划的末次访视或试验流程后视为"
                    "该例受试者完成试验；最后一例受试者完成后视为整个试验"
                    "结束。",
                    "confidence": 0.9,
                    "uncertainty": "当前证据包未检索到末次访视与具体访视名称"
                    "之间的对应条款。",
                    "user_action": "请确认末次访视是否等同于第24周访视或需结合"
                    "其他完成路径解释。",
                    "evidence_ids": ["e-completion-end"],
                },
                {
                    "claim_id": "clm_completion_gap",
                    "kind": "data_gap",
                    "text": "当前证据包未检索到将末次访视完成判定与受试者结束"
                    "路径相互衔接的操作细则。",
                    "confidence": 0.6,
                    "uncertainty": "可能存在于未纳入本证据包的章节或SOP中。",
                    "user_action": "如需用于监查判定，请补充检索受试者完成和试验"
                    "结束相关章节。",
                    "evidence_ids": ["e-completion-end"],
                },
            ],
        )
    )
    return [
        candidate(
            "计划访视时间窗：双盲治疗期第2、4、8周访视",
            "当前受试者在双盲治疗期应按第1.2节试验流程表进行第2周、第4周"
            "和第8周计划访视；对应访视日分别为D15±3天、D29±3天和D57±3天。"
            "所有访视均应在试验流程表规定的时间窗内进行，并应尽一切努力让"
            "每名受试者按计划参加每次访视。",
            {
                "clause_id": "visit_window_db_w2_w4_w8",
                "fact_type": "visit_window",
                "subject_scope": "进入双盲治疗期的受试者",
                "conditions": [
                    "受试者处于双盲治疗期",
                    "访视为方案规定的第2周、第4周或第8周访视",
                ],
                "time_windows": [
                    "第2周访视：D15±3天",
                    "第4周访视：D29±3天",
                    "第8周访视：D57±3天",
                    "所有访视应在第1.2节试验流程表规定的时间窗内进行",
                ],
                "thresholds": [
                    "D15允许偏差±3天",
                    "D29允许偏差±3天",
                    "D57允许偏差±3天",
                ],
                "exceptions": [],
                "required_actions": [
                    "按第1.2节试验流程表完成相应计划访视",
                    "尽一切努力让受试者按计划参加每次访视",
                ],
                "evidence_ids": [
                    "e-week-db",
                    "e-visit-schedule-ref",
                    "e-all-windows",
                ],
                "source_conflicts": [],
            },
            [
                {
                    "claim_id": "clm_db_window_fact",
                    "kind": "fact",
                    "text": "双盲治疗期第2、4、8周访视分别对应D15±3天、D29±3天"
                    "和D57±3天，且所有访视应在试验流程表规定的时间窗内进行。",
                    "confidence": 0.95,
                    "uncertainty": "当前证据包未包含第1.2节试验流程表逐行原文，"
                    "具体访视名称与程序清单未在本候选中展开。",
                    "user_action": "请核对第1.2节试验流程表中相应访视行的访视"
                    "名称、日期和窗口是否与本候选一致。",
                    "evidence_ids": [
                        "e-week-db",
                        "e-visit-schedule-ref",
                        "e-all-windows",
                    ],
                },
                {
                    "claim_id": "clm_db_window_scope_inference",
                    "kind": "inference",
                    "text": "该时间窗适用于双盲治疗期内需要返回研究中心完成计划"
                    "访视的受试者。",
                    "confidence": 0.8,
                    "uncertainty": "原文未在本证据包中单独列出每次双盲访视的适用"
                    "亚组；推断基于段落中‘双盲治疗期’和‘所有访视’措辞。",
                    "user_action": "请确认是否所有随机后进入双盲治疗期的受试者均"
                    "适用该时间窗。",
                    "evidence_ids": ["e-week-db", "e-all-windows"],
                },
            ],
        ),
        candidate(
            open_label_title,
            open_label_text,
            {
                "clause_id": "visit_window_ol_w12_w16_w20_w24",
                "fact_type": "visit_window",
                "subject_scope": open_label_scope,
                "conditions": open_label_conditions,
                "time_windows": [
                    "第12周访视：D85±7天",
                    "第16周访视：D113±7天",
                    "第20周访视：D141±7天",
                    "第24周访视：D169±7天",
                    "所有访视应在第1.2节试验流程表规定的时间窗内进行",
                ],
                "thresholds": [
                    "D85允许偏差±7天",
                    "D113允许偏差±7天",
                    "D141允许偏差±7天",
                    "D169允许偏差±7天",
                ],
                "exceptions": [],
                "required_actions": [
                    "按第1.2节试验流程表完成相应计划访视",
                    "尽一切努力让受试者按计划参加每次访视",
                ],
                "evidence_ids": [
                    "e-week-ol-preg",
                    "e-week-ol-days",
                    "e-visit-schedule-ref",
                    "e-all-windows",
                ],
                "source_conflicts": [],
            },
            operative_claims([
                {
                    "claim_id": "clm_ol_window_fact",
                    "kind": "fact",
                    "text": open_label_fact_text,
                    "confidence": 0.95,
                    "uncertainty": "当前证据包未包含第1.2节试验流程表逐行原文，"
                    "具体访视名称与程序清单未在本候选中展开。",
                    "user_action": "请核对第1.2节试验流程表中相应访视行的访视"
                    "名称、日期和窗口是否与本候选一致。",
                    "evidence_ids": [
                        "e-week-ol-preg",
                        "e-week-ol-days",
                        "e-visit-schedule-ref",
                        "e-all-windows",
                    ],
                },
                {
                    "claim_id": "clm_ol_window_scope_inference",
                    "kind": "inference",
                    "text": "该时间窗适用于完成双盲治疗期后进入开放治疗期的受试者。",
                    "confidence": 0.78,
                    "uncertainty": "本证据包中开放治疗期进入条件主要与疗效评估相关，"
                    "未逐条绑定所有开放期访视的适用对象。",
                    "user_action": "请确认开放治疗期访视时间窗是否适用于全部进入开放"
                    "治疗期的受试者。",
                    "evidence_ids": [
                        "e-week-ol-preg",
                        "e-week-ol-days",
                        "e-all-windows",
                    ],
                },
            ]),
        ),
        candidate(
            reschedule_title,
            reschedule_text,
            {
                "clause_id": "visit_reschedule_general",
                "fact_type": "visit_schedule",
                "subject_scope": "无法在试验流程表规定窗口内到院的受试者",
                "conditions": [
                    "受试者无法在第1.2节试验流程表规定的访视窗口期内前往研究中心",
                ],
                "time_windows": ["重新安排的访视应尽可能接近原始访视日"],
                "thresholds": [],
                "exceptions": ["受试者不应因排程困难而错过方案规定的访视"],
                "required_actions": [
                    "可在另一时间重新安排访视",
                    "尽一切努力重新安排尽可能接近原始访视日",
                    "避免因排程困难导致方案规定访视缺失",
                ],
                "evidence_ids": [
                    "e-all-windows",
                    "e-reschedule-dispense",
                    "e-visit-schedule-ref",
                ],
                "source_conflicts": [],
            },
            operative_claims([
                {
                    "claim_id": "clm_reschedule_fact",
                    "kind": "fact",
                    "text": "方案允许在受试者无法按规定窗口到院时改期，并要求改期尽可能"
                    "接近原始访视日，且不应因排程困难错过方案规定访视。",
                    "confidence": 0.93,
                    "uncertainty": "原文未给出改期后的最大允许间隔、是否可超出原访视"
                    "窗口或如何记录改期原因。",
                    "user_action": "请确认是否需要结合第1.2节试验流程表或中心SOP补充"
                    "改期记录与可接受延迟范围。",
                    "evidence_ids": ["e-all-windows", "e-reschedule-dispense"],
                },
                {
                    "claim_id": "clm_reschedule_duplicate_inference",
                    "kind": "inference",
                    "text": "两段相近原文均表达同一改期原则，可视为同一要求在不同章节"
                    "重复出现。",
                    "confidence": 0.72,
                    "uncertainty": "一处与访视时间表相邻，另一处与研究中心访视安排相邻；"
                    "未检索到明确条款说明二者适用范围不同。",
                    "user_action": "请确认是否将两处原文合并为统一改期原则，或分别"
                    "适用于不同访视场景。",
                    "evidence_ids": ["e-all-windows", "e-reschedule-dispense"],
                },
            ]),
        ),
        candidate(
            "计划外访视：研究者可根据安全需要增加访视",
            "出于对受试者安全的考虑，研究者可根据实际需要增加对受试者的访视"
            "次数，即计划外访视。研究者应在研究文件中对受试者的每次计划外"
            "访视内容进行记录。",
            {
                "clause_id": "visit_unscheduled_investigator",
                "fact_type": "visit_schedule",
                "subject_scope": "研究期间需要额外访视的受试者",
                "conditions": [
                    "出于受试者安全考虑",
                    "研究者根据实际需要判断需增加访视次数",
                ],
                "time_windows": [],
                "thresholds": [],
                "exceptions": [],
                "required_actions": [
                    "增加访视次数作为计划外访视",
                    "在研究文件中记录每次计划外访视内容",
                ],
                "evidence_ids": [
                    "e-unscheduled-title",
                    "e-unscheduled",
                ],
                "source_conflicts": [],
            },
            operative_claims([
                {
                    "claim_id": "clm_unscheduled_fact",
                    "kind": "fact",
                    "text": "研究者可基于安全考虑增加计划外访视，并应记录每次计划外"
                    "访视内容。",
                    "confidence": 0.94,
                    "uncertainty": "原文未列出计划外访视必须执行的程序、是否计入访视"
                    "序列或是否适用固定时间窗。",
                    "user_action": "请确认计划外访视是否需要按试验流程表中的特定程序执行。",
                    "evidence_ids": ["e-unscheduled-title", "e-unscheduled"],
                },
                {
                    "claim_id": "clm_unscheduled_context_inference",
                    "kind": "inference",
                    "text": "其他段落提及研究者可能要求受试者参加计划外访视，但多与"
                    "皮损评估或治疗决策语境相邻；本候选仅结构化独立的计划外访视"
                    "记录要求。",
                    "confidence": 0.68,
                    "uncertainty": "相邻语境可能隐含额外触发场景，但本候选未将其作为"
                    "独立条件纳入。",
                    "user_action": "请确认是否需要结合皮损评估相关段落补充计划外访视"
                    "触发场景。",
                    "evidence_ids": ["e-unscheduled-title", "e-unscheduled"],
                },
            ]),
        ),
        completion_end_candidate,
    ]


def test_v10_v9_repair_output_replay_original_fails_on_completion_end(
    tmp_path: Path,
) -> None:
    """The exact v9 terminal repaired five-candidate output is replayed
    against the v10 contract: candidate 3 (计划访视改期与补访原则) no longer
    fails the one-family gate (its decisive sentence is now a reschedule
    reference complement) but still fails deterministically because its
    title expands 重新安排 into 补访 while none of its bound evidence quotes
    supports 补访; candidate 5 (计划访视完成与试验结束判定) fails the visit
    topic boundary for completion/end facts. Zero candidates persist."""
    payload = _visit_v3_payload(
        [
            _paragraph(evidence_id, quote, paragraph_index=100 + index)
            for index, (evidence_id, quote) in enumerate(
                V10_VISIT_V9_REPLAY_EVIDENCE
            )
        ]
    )

    def original(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"] = _v9_replay_candidates(
            output,
            cleaned=False,
        )
        return output

    provider = FakeProvider([original, original])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v10-v9-replay-original",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "candidate 5 (计划访视完成与试验结束判定):" in (
        result.job.failure_message
    )
    assert (
        "subject completion, study completion/end or study start/end "
        "determination content" in result.job.failure_message
    )
    assert "candidate 3 (计划访视改期与补访原则):" in (
        result.job.failure_message
    )
    assert (
        "visit protocol candidate uses 补访 without a bound evidence "
        "quote that directly supports the makeup-visit term"
        in result.job.failure_message
    )
    assert service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    ) == ()


def test_v10_v9_repair_output_replay_cleaned_passes(
    tmp_path: Path,
) -> None:
    """The truly source-faithful five-candidate replay - candidates 1 and 4
    with only their directly supported fact claim, candidate 3 without the
    unsupported 补访 title expansion, the invented 为原始参照 sentence and
    the repeated-context duplicate inference, and candidate 5 replaced by a
    genuine retrieval gap - completes under the v10 contract. No candidate
    is accepted merely through a title-only family hit."""
    payload = _visit_v3_payload(
        [
            _paragraph(evidence_id, quote, paragraph_index=100 + index)
            for index, (evidence_id, quote) in enumerate(
                V10_VISIT_V9_REPLAY_EVIDENCE
            )
        ]
    )

    def cleaned(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        output["candidates"] = _v9_replay_candidates(
            output,
            cleaned=True,
        )
        return output

    provider = FakeProvider([cleaned])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v10-v9-replay-cleaned",
    )
    result = service.run_next("worker-a")
    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 1
    persisted = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )
    assert len(persisted) == 5
    assert {
        candidate.title for candidate in persisted
    } == {
        "计划访视时间窗：双盲治疗期第2、4、8周访视",
        "计划访视时间窗：第12、16、20、24周访视",
        "计划访视改期原则",
        "计划外访视：研究者可根据安全需要增加访视",
        "第1.2节试验流程表逐行访视清单：检索缺口",
    }
    by_title = {candidate.title: candidate for candidate in persisted}
    reschedule = by_title["计划访视改期原则"]
    assert "时间窗为原始参照" not in reschedule.text
    assert "补访" not in reschedule.text
    assert len(reschedule.claims) == 1
    open_label = by_title["计划访视时间窗：第12、16、20、24周访视"]
    # The phase premise 开放治疗期 is gone from every user-visible and
    # structured field because no replay-packet evidence supports it.
    assert "开放治疗期" not in open_label.title
    assert "开放治疗期" not in open_label.text
    assert "开放治疗期" not in open_label.structured_payload["subject_scope"]
    assert all(
        "开放治疗期" not in str(item)
        for item in open_label.structured_payload["conditions"]
    )
    assert "开放治疗期" not in "\n".join(
        claim.text for claim in open_label.claims
    )
    assert len(open_label.claims) == 1
    assert "第24周访视：D169±7天" in open_label.structured_payload["time_windows"]
    unscheduled = by_title["计划外访视：研究者可根据安全需要增加访视"]
    assert len(unscheduled.claims) == 1
    assert "皮损评估" not in unscheduled.claims[0].text


def test_v7_visit_first_dose_in_uncertainty_fails_medication_not_family(
    tmp_path: Path,
) -> None:
    """Gap 1: first-dose/IP content only in claim uncertainty fails the
    medication boundary; the operative family view stays single schedule."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            uncertainty="受试者第1天进行首次给药。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-boundary-uncertainty",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert (
        "study-treatment or concomitant-medication actions"
        in job.failure_message
    )
    assert "exactly one visit action family" not in job.failure_message


def test_v7_visit_collection_in_user_action_fails_collection_not_family(
    tmp_path: Path,
) -> None:
    """Gap 1: distributed AE/CM collection wording only in user_action fails
    the collection boundary; the operative family view stays single."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            user_action="请记录受试者的AE和合并用药情况。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-boundary-user-action",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    assert "AE or CM" in job.failure_message
    assert "exactly one visit action family" not in job.failure_message


def test_v7_visit_withdrawal_in_uncertainty_fails_withdrawal_boundary(
    tmp_path: Path,
) -> None:
    """Gap 1: consent-withdrawal variant only in claim uncertainty fails the
    withdrawal boundary without touching family classification."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            uncertainty="受试者撤回知情同意。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-boundary-withdrawal-uncertainty",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert "withdrawal content" in job.failure_message
    assert "exactly one visit action family" not in job.failure_message


def test_v7_visit_review_text_reschedule_and_unscheduled_keep_single_family(
    tmp_path: Path,
) -> None:
    """Gap 1: reschedule and unscheduled phrases only in claim
    uncertainty/user_action must not create extra families; a pure schedule
    candidate passes the whole visit gate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            uncertainty="计划外访视安排与补访安排均需记录。",
            user_action="请医学经理确认计划外访视和补访记录要求。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-review-text-family",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


def test_v7_visit_multi_candidate_mixed_failure_classes_single_repair(
    tmp_path: Path,
) -> None:
    """Gap 2: schema, forged-lineage, topic+generic and generic failures in
    distinct candidates all reach the single repair with stable candidate
    index/title; blocked candidates do not cascade into dependent checks."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            ),
            _paragraph(
                "evidence-2",
                "漏访受试者安排补访。",
                paragraph_index=101,
            ),
            _paragraph(
                "evidence-3",
                "受试者提前退出安排。",
                paragraph_index=102,
            ),
            _paragraph(
                "evidence-4",
                "计划外访视单独记录。",
                paragraph_index=103,
            ),
            _paragraph(
                "evidence-5",
                "计划外访视单独记录。",
                paragraph_index=104,
            ),
            _paragraph(
                "evidence-6",
                "（1）免疫抑制剂；",
                paragraph_index=105,
                roles=["list_item"],
            ),
        ]
    )

    def invalid_multi(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        base_claim = output["candidates"][0]["claims"][0]
        output["candidates"] = [
            {
                "candidate_type": "protocol_clause_structure",
                "title": "结构损坏候选",
                "text": "计划访视应在允许时间窗内完成。",
                "structured_payload": {
                    "clause_id": "clause-g1",
                    "fact_type": "visit_schedule",
                    "conditions": [],
                    "time_windows": ["访视窗内"],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": [],
                    "evidence_ids": ["evidence-1"],
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": "claim-g1",
                        "evidence_ids": ["evidence-1"],
                    }
                ],
            },
            {
                "candidate_type": "protocol_clause_structure",
                "title": "伪造修复谱系候选",
                "text": "计划访视应在允许时间窗内完成。",
                "structured_payload": {
                    "clause_id": "clause-g2",
                    "fact_type": "visit_schedule",
                    "subject_scope": "所有已随机受试者",
                    "conditions": [],
                    "time_windows": ["访视窗内"],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": [],
                    "evidence_ids": ["evidence-2"],
                    "repair_lineage": {
                        "schema_version": (
                            "monitoring_protocol_structural_repair_v2"
                        )
                    },
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": "claim-g2",
                        "evidence_ids": ["evidence-2"],
                    }
                ],
            },
            {
                "candidate_type": "protocol_clause_structure",
                "title": "首次给药候选",
                "text": (
                    "计划访视应在允许时间窗内完成。"
                    "文本含monai_9f2e内部标识。"
                ),
                "structured_payload": {
                    "clause_id": "clause-g3",
                    "fact_type": "visit_schedule",
                    "subject_scope": "所有已随机受试者",
                    "conditions": [],
                    "time_windows": ["访视窗内"],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": ["第1天进行首次给药"],
                    "evidence_ids": ["evidence-3"],
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": "claim-g3",
                        "evidence_ids": ["evidence-3"],
                    }
                ],
            },
            {
                "candidate_type": "protocol_clause_structure",
                "title": "结构修复阻断候选",
                "text": "计划访视应在允许时间窗内完成。",
                "structured_payload": {
                    "clause_id": "clause-g4",
                    "fact_type": "visit_schedule",
                    "subject_scope": "所有已随机受试者",
                    "conditions": [],
                    "time_windows": ["访视窗内"],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": [],
                    "evidence_ids": ["evidence-6"],
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": "claim-g4",
                        "evidence_ids": ["evidence-6"],
                    }
                ],
            },
            {
                "candidate_type": "protocol_clause_structure",
                "title": "证据对象候选",
                "text": "计划访视应在允许时间窗内完成。",
                "structured_payload": {
                    "clause_id": "clause-g5",
                    "fact_type": "visit_schedule",
                    "subject_scope": "所有已随机受试者",
                    "conditions": [],
                    "time_windows": ["访视窗内"],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": [],
                    "evidence_ids": ["evidence-5"],
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": "claim-g5",
                        "evidence_ids": ["evidence-5"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "evidence-5",
                        "source_entry_id": "source-listing",
                        "source_content_sha256": SOURCE_HASH,
                        "locator": "docx:paragraph:104",
                        "quote": "计划外访视单独记录。",
                        "raw_fields": {},
                    }
                ],
            },
        ]
        return output

    def valid_repair(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
        )

    provider = FakeProvider([invalid_multi, valid_repair])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-visit-mixed-classes",
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    # Exactly one initial call plus one controlled repair.
    assert len(provider.envelopes) == 2
    validation_errors = provider.envelopes[1].payload["validation_errors"]
    markers = [
        "candidate 1 (结构损坏候选):",
        "candidate 2 (伪造修复谱系候选):",
        "candidate 3 (首次给药候选):",
        "candidate 4 (结构修复阻断候选):",
        "candidate 5 (证据对象候选):",
    ]
    for marker in markers:
        assert marker in validation_errors
    # Diagnostic marker positions strictly increase and each extracted block
    # ends at the next marker.
    positions = [validation_errors.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)
    for position, marker in enumerate(markers[:-1]):
        bounded = validation_errors[positions[position] : positions[position + 1]]
        assert markers[position + 1] not in bounded

    def block(marker: str) -> str:
        start = validation_errors.index(marker)
        ends = [
            validation_errors.index(other)
            for other in markers
            if other != marker
            and validation_errors.index(other) > start
        ]
        return validation_errors[start : (min(ends) if ends else len(validation_errors))]

    c1 = block("candidate 1 (结构损坏候选):")
    assert "subject_scope" in c1
    assert "visit protocol candidate" not in c1
    assert "exactly one visit action family" not in c1
    c2 = block("candidate 2 (伪造修复谱系候选):")
    assert "repair lineage fields" in c2
    assert "visit protocol candidate" not in c2
    c3 = block("candidate 3 (首次给药候选):")
    _assert_error_order(
        c3,
        "study-treatment or concomitant-medication actions",
        "must not expose internal IDs",
    )
    c4 = block("candidate 4 (结构修复阻断候选):")
    assert "requires a typed list identity" in c4
    assert "visit protocol candidate" not in c4
    c5 = block("candidate 5 (证据对象候选):")
    assert "must not generate evidence objects" in c5
    candidates = service.repository.candidates(
        "project-alpha",
        result.job.job_id,
    )
    assert len(candidates) == 1


@pytest.mark.parametrize(
    ("directive_text", "expects_medication_error"),
    (
        ("访视当天完成第一次应用研究药物", True),
        ("访视当天完成第一次用药", True),
        ("访视当天首次应用研究药物", True),
        ("口服研究药物", True),
        ("首次口服研究药物", True),
        ("接受研究治疗", True),
        ("受试者在研究中心使用新药盒中的研究药物", True),
        ("开始合并用药", True),
        ("新增合并用药", True),
        ("访视当天首次给药", True),
        ("首次给药时进行计划访视", False),
        ("首次给药日进行计划访视", False),
        ("接受研究药物时进行计划访视", False),
        ("研究药物给药日完成计划访视", False),
        ("研究药物给药前7天内完成计划访视", False),
        ("首次给药之前7天内完成计划访视", False),
        ("首次给药的前7天内完成计划访视", False),
        ("接受研究药物后7天完成计划访视", False),
    ),
)
def test_v7_visit_common_chinese_administration_probes(
    tmp_path: Path,
    directive_text: str,
    expects_medication_error: bool,
) -> None:
    """Common protocol Chinese: oral/first-dose and bounded IP/CM treatment
    actions fail the medication boundary; relative timing anchors including
    时/日 must not suppress the actual directive 访视当天首次给药."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def build(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[directive_text],
        )

    if expects_medication_error:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build, build],
            "v7-visit-admin-probes",
        )
        assert job.status == MonitoringAiJobStatus.FAILED
        assert job.failure_code == "invalid_ai_output"
        assert (
            "study-treatment or concomitant-medication actions"
            in job.failure_message
        )
    else:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build],
            "v7-visit-admin-probes",
        )
        assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    ("withdrawal_text", "expects_withdrawal_error"),
    (
        ("受试者退出本研究", True),
        ("终止参与研究", True),
        ("停止参加研究", True),
        ("研究中心无法联系受试者", True),
        ("研究中心无法与受试者取得联系", True),
        ("撤回其知情同意", True),
        ("被判定为脱落", True),
        ("退出研究中心后回家", False),
        ("终止研究药物", False),
        ("停止参加研究中心会议", False),
        ("研究中心无法联系研究药物供应商", False),
        ("研究中心无法与研究药物供应商取得联系", False),
    ),
)
def test_v7_visit_common_chinese_withdrawal_probes(
    tmp_path: Path,
    withdrawal_text: str,
    expects_withdrawal_error: bool,
) -> None:
    """Withdrawal/consent/lost-follow-up forms fail; research-center and
    study-drug noun controls stay outside withdrawal classification."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def build(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[withdrawal_text],
        )

    if expects_withdrawal_error:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build, build],
            "v7-visit-withdrawal-probes",
        )
        assert job.status == MonitoringAiJobStatus.FAILED
        assert "withdrawal content" in job.failure_message
    else:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build],
            "v7-visit-withdrawal-probes",
        )
        assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    ("collection_text", "expects_collection_error"),
    (
        ("AE和合并用药均应予以记录", True),
        ("不良事件及伴随用药应进行收集", True),
        ("研究者应详细记录受试者报告的所有不良事件", True),
        ("AE", True),
        ("ae", True),
        ("CM", True),
        ("cm", True),
        ("CMV", False),
        ("记录CMV检测结果", False),
    ),
)
def test_v7_visit_common_chinese_collection_probes(
    tmp_path: Path,
    collection_text: str,
    expects_collection_error: bool,
) -> None:
    """Verb/object collection forms and standalone case-insensitive AE/CM
    tokens fail; the longer CMV token must not match."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def build(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=[collection_text],
        )

    if expects_collection_error:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build, build],
            "v7-visit-collection-probes",
        )
        assert job.status == MonitoringAiJobStatus.FAILED
        assert "AE or CM" in job.failure_message
    else:
        job, _provider = _run_visit_builder(
            tmp_path,
            payload,
            [build],
            "v7-visit-collection-probes",
        )
        assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "family_text",
    (
        "计划外的访视安排由研究者确认。",
        "临时访视。",
        "访视延期三天。",
        "调整访视日期。",
        "更改访视日期。",
        "修改访视日期。",
        "第2周访视。",
        "D15±3d访视。",
    ),
)
def test_v7_visit_common_chinese_family_probes_pass(
    tmp_path: Path,
    family_text: str,
) -> None:
    """计划外/临时访视 are unscheduled only; the visit-date verbs are
    reschedule only; week/day visit forms are schedule only."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def valid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=family_text,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [valid],
        "v7-visit-family-probes",
    )
    assert job.status == MonitoringAiJobStatus.COMPLETED


@pytest.mark.parametrize(
    "additional_family_text",
    (
        "访视延期三天",
        "调整访视日期",
        "更改访视日期",
        "修改访视日期",
        "临时访视",
    ),
)
def test_v7_visit_week_and_additional_family_combination_rejects(
    tmp_path: Path,
    additional_family_text: str,
) -> None:
    """A week-form schedule combined with a reschedule or unscheduled phrase
    still rejects with the exactly-one-family gate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text=f"第2周访视与{additional_family_text}合并条款。",
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-family-probes-reject",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert "exactly one visit action family" in job.failure_message


@pytest.mark.parametrize(
    ("required_actions", "expected_errors"),
    (
        (
            ("访视当天首次给药", "发放研究药物", "受试者撤回知情同意"),
            (
                "study-treatment or concomitant-medication actions",
                "dispensing",
                "withdrawal content",
            ),
        ),
        (
            ("药品发放", "失访"),
            ("dispensing", "withdrawal content"),
        ),
        (
            ("退出本研究", "安全性随访"),
            ("withdrawal content", "safety follow-up"),
        ),
        (
            ("安全性随访", "记录AE"),
            ("safety follow-up", "AE or CM"),
        ),
    ),
)
def test_v7_visit_error_precedence_combinations(
    tmp_path: Path,
    required_actions: Sequence[str],
    expected_errors: Sequence[str],
) -> None:
    """Documented precedence holds for common phrase combinations:
    medication→PK→withdrawal, PK→withdrawal, withdrawal→safety,
    safety→collection."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
            required_actions=required_actions,
        )

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-precedence-combos",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    for earlier, later in zip(expected_errors, expected_errors[1:]):
        _assert_error_order(job.failure_message, earlier, later)


def test_v7_visit_v6_repaired_shape_c1_c5(
    tmp_path: Path,
) -> None:
    """Exact v6 repaired-shape candidates from the independent review keep
    their documented first/ordered failures; a valid repair completes with
    exactly one persisted candidate."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "第2周、第4周和第8周访视应在允许时间窗内完成。",
                paragraph_index=100,
            ),
            _paragraph(
                "evidence-2",
                "第12周、第16周、第20周和第24周访视按时间窗完成。",
                paragraph_index=101,
            ),
            _paragraph(
                "evidence-3",
                "受试者撤回其知情同意后需进行安全性随访电话。",
                paragraph_index=102,
            ),
            _paragraph(
                "evidence-4",
                "被判定为脱落的受试者安排计划访视与计划外访视。",
                paragraph_index=103,
            ),
            _paragraph(
                "evidence-5",
                "研究中心于访视当天完成第一次应用研究药物。",
                paragraph_index=104,
            ),
        ]
    )

    def invalid_multi(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        base_claim = output["candidates"][0]["claims"][0]

        def candidate(
            index: int,
            title: str,
            text: str,
            required_actions: Sequence[str],
        ) -> Dict[str, Any]:
            evidence_id = f"evidence-{index}"
            return {
                "candidate_type": "protocol_clause_structure",
                "title": title,
                "text": text,
                "structured_payload": {
                    "clause_id": f"clause-c{index}",
                    "fact_type": "visit_schedule",
                    "subject_scope": "所有已随机受试者",
                    "conditions": [],
                    "time_windows": [],
                    "thresholds": [],
                    "exceptions": [],
                    "required_actions": list(required_actions),
                    "evidence_ids": [evidence_id],
                },
                "claims": [
                    {
                        **base_claim,
                        "claim_id": f"claim-c{index}",
                        "evidence_ids": [evidence_id],
                    }
                ],
            }

        output["candidates"] = [
            candidate(
                1,
                "clause_visit_window_blinded_w2_w4_w8",
                "第2周、第4周和第8周访视应在允许时间窗内完成；"
                "漏访受试者安排补访。",
                ("第一次应用研究药物",),
            ),
            candidate(
                2,
                "clause_visit_window_open_w12_w16_w20_w24",
                "第12周、第16周、第20周和第24周访视按时间窗完成；"
                "改期访视应重新安排。",
                ("第一次应用研究药物",),
            ),
            candidate(
                3,
                "clause_safety_followup_call",
                "受试者撤回其知情同意后需进行安全性随访电话。",
                (),
            ),
            candidate(
                4,
                "clause_early_exit_lost_unscheduled_visit",
                "被判定为脱落的受试者安排计划访视与计划外访视。",
                (),
            ),
            candidate(
                5,
                "clause_visit_first_dose_site",
                "研究中心于访视当天完成第一次应用研究药物。",
                (),
            ),
        ]
        return output

    def valid_repair(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            text="计划访视应在允许时间窗内完成。",
            time_windows=["访视窗内"],
        )

    provider = FakeProvider([invalid_multi, valid_repair])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-visit-c1-c5-shapes",
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.COMPLETED
    assert len(provider.envelopes) == 2
    validation_errors = provider.envelopes[1].payload["validation_errors"]
    markers = [
        "candidate 1 (clause_visit_window_blinded_w2_w4_w8):",
        "candidate 2 (clause_visit_window_open_w12_w16_w20_w24):",
        "candidate 3 (clause_safety_followup_call):",
        "candidate 4 (clause_early_exit_lost_unscheduled_visit):",
        "candidate 5 (clause_visit_first_dose_site):",
    ]
    for marker in markers:
        assert marker in validation_errors

    def block(marker: str) -> str:
        start = validation_errors.index(marker)
        ends = [
            validation_errors.index(other)
            for other in markers
            if other != marker
            and validation_errors.index(other) > start
        ]
        return validation_errors[
            start : (min(ends) if ends else len(validation_errors))
        ]

    c1 = block(markers[0])
    _assert_error_order(
        c1,
        "study-treatment or concomitant-medication actions",
        "exactly one visit action family",
    )
    c2 = block(markers[1])
    _assert_error_order(
        c2,
        "study-treatment or concomitant-medication actions",
        "exactly one visit action family",
    )
    c3 = block(markers[2])
    _assert_error_order(c3, "withdrawal content", "safety follow-up")
    _assert_error_order(
        c3,
        "safety follow-up",
        "exactly one visit action family",
    )
    c4 = block(markers[3])
    _assert_error_order(
        c4,
        "withdrawal content",
        "exactly one visit action family",
    )
    c5 = block(markers[4])
    _assert_error_order(
        c5,
        "study-treatment or concomitant-medication actions",
        "exactly one visit action family",
    )
    assert len(
        service.repository.candidates("project-alpha", result.job.job_id)
    ) == 1


def test_v7_c3_shape_structural_closure_8_to_15_before_topic_failure(
    tmp_path: Path,
) -> None:
    """C3-shaped selection: 8 provider-selected table cells expand
    deterministically to 15 (rows plus headers) before the topic gate fails
    with withdrawal, safety and family errors in documented order."""
    payload = _visit_v3_payload(
        [
            _table_cell(
                f"evidence-{index}",
                f"表头{index}",
                table_index=4,
                row_index=0,
                cell_index=cell,
                roles=["table_header"],
            )
            for index, cell in enumerate(range(7), start=1)
        ]
        + [
            _table_cell(
                f"evidence-{index}",
                f"单元格{index}",
                table_index=4,
                row_index=1,
                cell_index=cell,
                roles=["primary_match", "table_row_context"],
            )
            for index, cell in enumerate(range(8), start=8)
        ],
    )
    selected = [f"evidence-{index}" for index in range(8, 16)]
    assert len(selected) == 8
    repaired = monitoring_ai_service_module.repair_protocol_structural_bundles(
        selected,
        payload["evidence_packet"],
    )
    assert len(repaired.expanded_evidence_ids) == 15
    assert set(repaired.expanded_evidence_ids) == {
        f"evidence-{index}" for index in range(1, 16)
    }

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        output = _valid_output(envelope)
        candidate = output["candidates"][0]
        candidate["title"] = "clause_safety_followup_call"
        candidate["text"] = "受试者撤回其知情同意后需进行安全性随访电话。"
        candidate["structured_payload"].update(
            {
                "time_windows": [],
                "required_actions": [],
                "evidence_ids": list(selected),
            }
        )
        candidate["claims"][0]["evidence_ids"] = list(selected)
        return output

    job, _provider = _run_visit_builder(
        tmp_path,
        payload,
        [invalid, invalid],
        "v7-visit-c3-closure",
    )
    assert job.status == MonitoringAiJobStatus.FAILED
    assert job.failure_code == "invalid_ai_output"
    _assert_error_order(
        job.failure_message,
        "withdrawal content",
        "safety follow-up",
    )
    _assert_error_order(
        job.failure_message,
        "safety follow-up",
        "exactly one visit action family",
    )
    # The repair completed (15 expanded IDs) before topic validation: the
    # failure is the topic gate, not a structural repair error.
    assert "requires a typed list identity" not in job.failure_message


def test_v7_visit_sdtm_assertion_candidate_indexed(tmp_path: Path) -> None:
    """A forbidden SDTM assertion in candidate text is reported under the
    candidate's own index/title in the single repair diagnostic."""
    payload = _visit_v3_payload(
        [
            _paragraph(
                "evidence-1",
                "计划访视应在时间窗内完成。",
                paragraph_index=100,
            )
        ]
    )

    def invalid(envelope: AiPromptEnvelope) -> Dict[str, Any]:
        return _visit_output(
            envelope,
            title="SDTM断言候选",
            text="该文件是SDTM。",
            time_windows=["访视窗内"],
        )

    provider = FakeProvider([invalid, invalid])
    service = _service(tmp_path, provider)
    service.submit_task(
        project_id="project-alpha",
        task_type=MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
        input_revision=_revision(),
        input_payload=payload,
        business_key="v7-visit-sdtm-indexed",
    )
    result = service.run_next("worker-a")

    assert result.job is not None
    assert result.job.status == MonitoringAiJobStatus.FAILED
    assert result.job.failure_code == "invalid_ai_output"
    assert "candidate 1 (SDTM断言候选):" in result.job.failure_message
    assert "must not be asserted to be SDTM" in result.job.failure_message
    assert (
        service.repository.candidates("project-alpha", result.job.job_id)
        == ()
    )
