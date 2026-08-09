from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.api.app.ai_gateway import AiPromptEnvelope, AiProviderRuntimeError
from services.api.app.monitoring_ai_contracts import MONITORING_AI_SCHEMA_VERSION
from services.api.app.monitoring_ai_service import MonitoringAiRuntimeBinding
from tools.run_monitoring_real_ai_field_mapping import (
    BenchmarkConfig,
    RESULT_SCHEMA_VERSION,
    run_benchmark,
)


class _FakeFieldMappingProvider:
    provider_name = "fake-independent-provider"
    model_name = "fake-field-mapping-model"
    expected_response_model = "fake-field-mapping-model"
    response_model = "fake-field-mapping-model"
    transport_name = "openai_compatible"

    def __init__(self) -> None:
        self.envelopes: list[AiPromptEnvelope] = []

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        self.envelopes.append(envelope)
        original = envelope.payload.get("original_task", envelope.payload)
        profile = original["input_payload"]["field_profile"]
        mappings = [
            {
                "domain": field["domain"],
                "source_field": field["field"],
                "recommended_role": (
                    "edc_domain_code"
                    if field["field"].upper() == "DOMAIN"
                    else "source_field_candidate"
                ),
                "field_kind": (
                    "source_metadata"
                    if field["field"].startswith("__")
                    or field["field"].upper() == "DOMAIN"
                    else "source_collected"
                ),
                "confidence": 0.76,
                "uncertainty": "仍需结合项目数据字典确认字段语义。",
                "user_action": "请确认或修订字段角色。",
                "related_fields": [],
                "evidence_ids": [],
                "standards_reference": None,
                "derivation_lineage": None,
            }
            for field in profile["fields"]
        ]
        return {
            "schema_version": MONITORING_AI_SCHEMA_VERSION,
            "task_id": envelope.task_id,
            "task_type": "listing_field_mapping",
            "input_revision_sha256": original["input_revision_sha256"],
            "candidates": [
                {
                    "candidate_type": "listing_field_mapping_set",
                    "title": "字段映射建议",
                    "text": "供医学经理确认来源字段语义。",
                    "structured_payload": {"field_mappings": mappings},
                }
            ],
        }


class _FailingProvider(_FakeFieldMappingProvider):
    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        self.envelopes.append(envelope)
        raise AiProviderRuntimeError(
            "provider failed near /Users/example/private/runtime and "
            "secret=fake-secret Authorization: Bearer fake-bearer-token"
        )


def _runtime() -> MonitoringAiRuntimeBinding:
    return MonitoringAiRuntimeBinding(
        profile_id="independent-ai-test-profile",
        provider="fake-independent-provider",
        model="fake-field-mapping-model",
        env={
            "WORKBENCH_AI_PROVIDER": "fake-independent-provider",
            "WORKBENCH_AI_TRANSPORT": "openai_compatible",
            "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
            "WORKBENCH_AI_MODEL": "fake-field-mapping-model",
            "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "fake-field-mapping-model",
            "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            "WORKBENCH_AI_API_KEY": "fake-secret",
        },
    )


def _listing(path: Path) -> Path:
    path.write_text(
        (
            "__STUDYOID,__STUDYEVENTOID,__STUDYEVENTREPEATKEY,DOMAIN,"
            "USUBJID,PAGE,FORM,LINE,AETERM,AESEV\n"
            "STUDY-1,V1,1,AE,S01001,AE,AE,1,头痛,轻度\n"
            "STUDY-1,V1,1,AE,S01002,AE,AE,1,皮疹,中度\n"
            "STUDY-1,V1,1,CM,S01001,CM,CM,1,氨氯地平,\n"
        ),
        encoding="utf-8",
    )
    return path


def test_benchmark_reparses_freezes_profiles_and_writes_redacted_success_result(
    tmp_path: Path,
) -> None:
    listing = _listing(tmp_path / "original-listing.csv")
    output_dir = tmp_path / "result"
    provider = _FakeFieldMappingProvider()

    exit_code, result = run_benchmark(
        BenchmarkConfig(
            project_id="project-benchmark",
            listing_path=listing,
            domain="AE",
            chunk_index=2,
            chunk_size=4,
            output_dir=output_dir,
        ),
        runtime_resolver=_runtime,
        provider_factory=lambda _: provider,
    )

    assert exit_code == 0
    assert result["success"] is True
    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["source"]["file_name"] == listing.name
    assert len(result["source"]["content_sha256"]) == 64
    assert result["profile"]["schema_version"] == "monitoring_ai_field_profile_v3"
    assert result["profile"]["row_count"] == 3
    assert result["profile"]["domain_count"] == 2
    assert result["profile"]["field_count"] >= 10
    assert result["target_chunk"]["domain"] == "AE"
    assert result["target_chunk"]["chunk_index"] == 2
    assert 1 <= result["target_chunk"]["field_count"] <= 4
    assert result["job"]["status"] == "completed"
    assert result["job"]["provider"] == "fake-independent-provider"
    assert result["job"]["requested_model"] == "fake-field-mapping-model"
    assert result["candidates"][0]["field_mappings"]
    assert all(
        mapping["evidence_summary"]
        for mapping in result["candidates"][0]["field_mappings"]
    )
    assert len(provider.envelopes) == 1

    stored = json.loads((output_dir / "RESULT.json").read_text(encoding="utf-8"))
    serialized = json.dumps(stored, ensure_ascii=False)
    assert stored == result
    assert str(tmp_path) not in serialized
    assert str(listing.resolve()) not in serialized
    assert "fake-secret" not in serialized
    assert not list(output_dir.glob(".monitoring-field-mapping-benchmark-*"))


def test_benchmark_failure_writes_result_and_returns_nonzero_without_credentials_or_paths(
    tmp_path: Path,
) -> None:
    listing = _listing(tmp_path / "failure-listing.csv")
    output_dir = tmp_path / "failure-result"
    provider = _FailingProvider()

    exit_code, result = run_benchmark(
        BenchmarkConfig(
            project_id="project-failure",
            listing_path=listing,
            domain="AE",
            chunk_index=1,
            chunk_size=12,
            output_dir=output_dir,
        ),
        runtime_resolver=_runtime,
        provider_factory=lambda _: provider,
    )

    assert exit_code != 0
    assert result["success"] is False
    assert result["job"]["status"] == "failed"
    assert result["error"]["code"] == "provider_runtime_error"
    assert len(result["failure_attempts"]) == 2
    assert all(
        attempt["failure_code"] == "provider_runtime_error"
        for attempt in result["failure_attempts"]
    )
    assert len(provider.envelopes) == 2

    stored_text = (output_dir / "RESULT.json").read_text(encoding="utf-8")
    stored = json.loads(stored_text)
    assert stored["success"] is False
    assert stored["job"]["status"] == "failed"
    assert "/Users/example" not in stored_text
    assert str(tmp_path) not in stored_text
    assert "fake-secret" not in stored_text
    assert "fake-bearer-token" not in stored_text
    assert "secret=<redacted>" in stored_text


def test_benchmark_invalid_chunk_still_writes_failure_result(tmp_path: Path) -> None:
    listing = _listing(tmp_path / "invalid-chunk.csv")
    output_dir = tmp_path / "invalid-result"

    exit_code, result = run_benchmark(
        BenchmarkConfig(
            project_id="project-invalid",
            listing_path=listing,
            domain="AE",
            chunk_index=1,
            chunk_size=13,
            output_dir=output_dir,
        ),
        runtime_resolver=_runtime,
        provider_factory=lambda _: _FakeFieldMappingProvider(),
    )

    assert exit_code != 0
    assert result["success"] is False
    assert result["error"]["type"] == "ValueError"
    assert json.loads(
        (output_dir / "RESULT.json").read_text(encoding="utf-8")
    )["error"]["message"] == "chunk-size must be an integer from 1 to 12"
