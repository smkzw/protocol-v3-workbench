from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
    MedicalWritingAssessmentInstrumentUse,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)
from services.api.app.ai_execution_policy import (
    AiExecutionPolicyResolver,
    SERVER_PROMPT_VERSIONS,
)
from services.api.app.ai_gateway import (
    AiPromptEnvelope,
    AiTaskSpec,
    AiTaskType,
    PROTOCOL_SYNOPSIS_INSTRUMENT_ENDPOINT_PATHS,
    PROTOCOL_SYNOPSIS_INSTRUMENT_KINDS,
    PromptRegistry,
)
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
from services.api.app.demo_repository import DemoRepository


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]


def _source() -> AiTaskSourceRef:
    return AiTaskSourceRef(
        source_id="d017_synopsis_span_001",
        source_type="project_protocol_synopsis",
        title="CMS-D017-PNH方案摘要",
        locator="synopsis:d017:docx:table:3:row:8",
        text_preview="采用FACIT-F评价疲劳，作为普通次要终点。",
        project_id="proj_mgk10_sar_demo",
        module="medical_writing",
    )


def _instrument(*, endpoint_paths: list[str]) -> dict:
    return MedicalWritingAssessmentInstrumentUse(
        instrument_id="instrument_facit_f_d017",
        canonical_name_zh="慢性疾病治疗功能评估-疲劳量表",
        canonical_name_en="Functional Assessment of Chronic Illness Therapy-Fatigue",
        acronym="FACIT-F",
        instrument_kind="patient_reported",
        study_purpose="普通次要终点评价",
        endpoint_paths=["picos.other_secondary_endpoints"],
        evidence_span_ids=["sp_facit_f"],
    ).model_dump(mode="json") | {"endpoint_paths": endpoint_paths}


def _provider_output(
    envelope: AiPromptEnvelope,
    *,
    endpoint_paths: list[str],
) -> dict:
    source = envelope.payload["allowed_sources"][0]
    picos = MedicalWritingPicosDefinition().model_dump(mode="json")
    picos["assessment_instruments"] = [_instrument(endpoint_paths=endpoint_paths)]
    return {
        "task_id": envelope.task_id,
        "task_type": envelope.task_type.value,
        "provider": "buddy",
        "model": "deepseek-v4-pro",
        "prompt_version": envelope.prompt_version,
        "input_source_ids": [source["source_id"]],
        "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
        "findings": [],
        "evidence_spans": [
            {
                "span_id": "sp_facit_f",
                "source_id": source["source_id"],
                "locator": source["locator"],
                "quote": source["text_preview"],
            }
        ],
        "uncertainties": [],
        "needs_medical_confirmation": True,
        "schema_version": "ai_task_output_v0_1",
        "study_definition": {
            "framing": MedicalWritingStudyFraming().model_dump(mode="json"),
            "picos": picos,
            "synopsis_text": source["text_preview"],
            "missing_fields": [],
            "conflict_notes": [],
            "field_evidence_span_ids": {
                "picos.assessment_instruments": ["sp_facit_f"],
            },
        },
    }


class _NestedContractRepairProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self, *, keep_invalid: bool = False):
        self.keep_invalid = keep_invalid
        self.envelopes: list[AiPromptEnvelope] = []

    def run(self, envelope: AiPromptEnvelope) -> dict:
        self.envelopes.append(envelope)
        if len(self.envelopes) == 1 or self.keep_invalid:
            endpoint_paths = ["picos.key_secondary_endpoints"]
        else:
            endpoint_paths = ["picos.other_secondary_endpoints"]
        return _provider_output(envelope, endpoint_paths=endpoint_paths)


def _runner(provider: _NestedContractRepairProvider, tmpdir: str) -> AiTaskRunner:
    policy = AiExecutionPolicyResolver(
        deployment_profile="local_private_clinical",
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        test_only_provider_injection=True,
    )
    return AiTaskRunner(
        DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
        AiTaskStore(Path(tmpdir) / "ai_runs.jsonl"),
        provider_factory=lambda resolution: provider,
        policy_resolver=policy,
    )


def _request() -> AiTaskRequest:
    return AiTaskRequest(
        module="medical_writing",
        task_type="protocol_synopsis_structuring",
        prompt_version="protocol_synopsis_structuring_v0_9",
        allowed_sources=[_source()],
        user_instruction="仅基于D017方案摘要提取研究定义候选。",
    )


def test_protocol_synopsis_v09_exposes_complete_machine_readable_instrument_schema():
    envelope = PromptRegistry().build(
        AiTaskSpec(
            task_id="task_d017_synopsis_v09",
            task_type=AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=[_source()],
        )
    )

    task_contract = envelope.payload["task_specific_output_contract"]
    schema = task_contract["assessment_instrument_item"]
    assert SERVER_PROMPT_VERSIONS[AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING].endswith(
        "_v0_9"
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(
        MedicalWritingAssessmentInstrumentUse.model_fields
    )
    assert schema["properties"]["instrument_kind"]["enum"] == list(
        PROTOCOL_SYNOPSIS_INSTRUMENT_KINDS
    )
    assert schema["properties"]["endpoint_paths"]["items"]["enum"] == list(
        PROTOCOL_SYNOPSIS_INSTRUMENT_ENDPOINT_PATHS
    )
    assert schema["x_endpoint_binding_semantics"] == {
        "canonical_prefix": "picos.",
        "ordinary_secondary_path": "picos.other_secondary_endpoints",
        "key_secondary_path": "picos.key_secondary_endpoints",
        "key_secondary_requires_explicit_source_label": True,
        "ordinary_secondary_must_not_be_upgraded": True,
        "unknown_relationship_value": [],
    }
    assert schema["examples"][0]["acronym"] == "FACIT-F"
    assert schema["examples"][0]["endpoint_paths"] == [
        "picos.other_secondary_endpoints"
    ]
    assert schema["examples"][1]["endpoint_paths"] == []
    assert schema["allOf"][0]["then"]["properties"]["endpoint_paths"]["not"][
        "contains"
    ] == {"const": "picos.key_secondary_endpoints"}
    assert {item["reason_code"] for item in schema["x_negative_examples"]} >= {
        "missing_picos_prefix",
        "ordinary_secondary_upgraded_to_key_secondary",
        "not_an_assessment_instrument",
    }
    assert "不得升级层级" in envelope.system_prompt
    assert "结构化字段值不是摘要改写" in envelope.system_prompt
    synopsis_field = task_contract["study_definition"]["fields"]["synopsis_text"]
    assert "must not compress" in synopsis_field
    assert "endpoint definitions" in synopsis_field
    assert "picos.primary_objectives" in envelope.system_prompt
    assert "开放标签、多剂量探索不得改写成双盲或安慰剂对照" in envelope.system_prompt
    assert "estimand_strategy必须保持空字符串" in envelope.system_prompt


@pytest.mark.parametrize(
    ("indication", "instrument"),
    [
        (
            "阵发性睡眠性血红蛋白尿症",
            MedicalWritingAssessmentInstrumentUse(
                instrument_id="instrument_facit_f_d017",
                canonical_name_zh="慢性疾病治疗功能评估-疲劳量表",
                acronym="FACIT-F",
                instrument_kind="patient_reported",
                endpoint_paths=["picos.other_secondary_endpoints"],
            ),
        ),
        (
            "类风湿关节炎",
            MedicalWritingAssessmentInstrumentUse(
                instrument_id="instrument_haq_di_ra",
                canonical_name_zh="健康评估问卷残疾指数",
                acronym="HAQ-DI",
                instrument_kind="patient_reported",
                endpoint_paths=["picos.other_secondary_endpoints"],
            ),
        ),
        (
            "特应性皮炎",
            MedicalWritingAssessmentInstrumentUse(
                instrument_id="instrument_easi_ad",
                canonical_name_zh="湿疹面积和严重程度指数",
                acronym="EASI",
                instrument_kind="clinician_reported",
                endpoint_paths=["picos.primary_endpoint"],
            ),
        ),
    ],
)
def test_pnh_ra_ad_assessment_instrument_fixtures_are_deterministic(
    indication: str,
    instrument: MedicalWritingAssessmentInstrumentUse,
):
    validated = MedicalWritingPicosDefinition(
        population_summary=indication,
        assessment_instruments=[instrument],
    )
    assert validated.assessment_instruments == [instrument]


def test_v09_contract_excludes_hb_ldh_pk_laboratory_and_ecg_from_instruments():
    envelope = PromptRegistry().build(
        AiTaskSpec(
            task_id="task_instrument_exclusions_v09",
            task_type=AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=[_source()],
        )
    )
    assert envelope.payload["task_specific_output_contract"][
        "assessment_instrument_exclusions"
    ] == [
        "hemoglobin_or_hb",
        "lactate_dehydrogenase_or_ldh",
        "pharmacokinetic_concentration_or_pk",
        "routine_laboratory_test",
        "electrocardiogram_or_ecg",
    ]


def test_nested_contract_repair_envelope_carries_exact_enums_and_hierarchy():
    provider = _NestedContractRepairProvider()
    with tempfile.TemporaryDirectory() as tmpdir:
        run = _runner(provider, tmpdir).submit_internal(
            "proj_mgk10_sar_demo",
            _request(),
        )

    assert run.status == AiTaskRunStatus.COMPLETED
    assert len(provider.envelopes) == 2
    nested = provider.envelopes[1].payload["repair_context"]["nested_contract"]
    assert nested["instrument_kind_enum"] == list(PROTOCOL_SYNOPSIS_INSTRUMENT_KINDS)
    assert nested["endpoint_paths_enum"] == list(
        PROTOCOL_SYNOPSIS_INSTRUMENT_ENDPOINT_PATHS
    )
    assert (
        nested["endpoint_binding_semantics"]["ordinary_secondary_must_not_be_upgraded"]
        is True
    )
    assert nested["endpoint_binding_semantics"]["unknown_relationship_value"] == []
    assert "服务端不会静默删除或改写非法绑定" in provider.envelopes[1].system_prompt


def test_second_invalid_nested_contract_output_still_fails_closed():
    provider = _NestedContractRepairProvider(keep_invalid=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        run = _runner(provider, tmpdir).submit_internal(
            "proj_mgk10_sar_demo",
            _request(),
        )

    assert run.status == AiTaskRunStatus.FAILED
    assert len(provider.envelopes) == 2
    assert any(
        "ordinary secondary endpoint must bind" in error
        for error in run.validation_errors
    )
