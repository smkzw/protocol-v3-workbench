from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver  # noqa: E402
from services.api.app.ai_gateway import (  # noqa: E402
    AiPromptEnvelope,
    AiProviderRuntimeError,
    AiTaskType,
    DisabledAiProvider,
)
from services.api.app.ai_task_runner import (  # noqa: E402
    AiTaskRunner,
    AiTaskStore,
    evidence_quote_matches_source,
    normalize_protocol_full_draft_evidence_ids,
    normalize_protocol_synopsis_missing_findings,
    normalize_single_source_medical_writing_candidates,
    strip_blank_greenfield_anchor_evidence,
    validate_medical_writing_revision_semantics,
    validate_protocol_synopsis_source_fidelity,
)
from services.api.app.demo_repository import DemoRepository  # noqa: E402


class FakeProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def run(self, envelope: AiPromptEnvelope):
        result = {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": ["protocol_span_001"],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "随机前需完成禁限用药洗脱",
                    "source_id": "protocol_span_001",
                    "evidence_span_ids": ["span_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": "protocol_span_001",
                    "locator": "docx:p120",
                    "quote": "随机前需完成禁限用药洗脱。",
                }
            ],
            "uncertainties": [
                {"level": "medical_review", "description": "需医学经理确认适用范围。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }
        return result


class ExtraSourceProvider(FakeProvider):
    def run(self, envelope: AiPromptEnvelope):
        output = super().run(envelope)
        output["input_source_ids"] = ["protocol_span_001", "unregistered_source"]
        return output


class RepairingSynopsisProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(
        self, *, always_invalid: bool = False, always_invalid_locator: bool = False
    ):
        self.always_invalid = always_invalid
        self.always_invalid_locator = always_invalid_locator
        self.envelopes = []

    def run(self, envelope: AiPromptEnvelope):
        self.envelopes.append(envelope)
        source = envelope.payload["allowed_sources"][0]
        quote = (
            "这不是方案摘要中的原文证据。"
            if self.always_invalid or len(self.envelopes) == 1
            else source["text_preview"]
        )
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [
                item["source_id"] for item in envelope.payload["allowed_sources"]
            ],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "synopsis_ev_1",
                    "source_id": source["source_id"],
                    "locator": (
                        "synopsis:source_1:docx:paragraph:999"
                        if self.always_invalid_locator
                        else source["locator"]
                    ),
                    "quote": quote,
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "study_definition": {
                "framing": MedicalWritingStudyFraming().model_dump(mode="json"),
                "picos": MedicalWritingPicosDefinition().model_dump(mode="json"),
                "synopsis_text": source["text_preview"],
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {},
            },
        }
class RepairingFullDraftProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self):
        self.envelopes = []

    def run(self, envelope: AiPromptEnvelope):
        self.envelopes.append(envelope)
        source = envelope.payload["allowed_sources"][0]
        section_ids = envelope.payload["task_context"]["section_ids"]
        proposal = "正文过短" if len(self.envelopes) == 1 else "本研究将依照已确认的研究设计实施。" * 8
        evidence_quote = (
            "这是对来源的概括而非逐字证据。"
            if len(self.envelopes) == 1
            else source["text_preview"]
        )
        result = {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [
                item["source_id"] for item in envelope.payload["allowed_sources"]
            ],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "full_draft_ev_1",
                    "source_id": source["source_id"],
                    "locator": source["locator"],
                    "quote": evidence_quote,
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {
                "sections": [
                    {
                        "section_id": section_id,
                        "content_status": "complete",
                        "proposal_text": proposal,
                        "rationale": "依据当前项目已确认研究事实形成章节候选。",
                        "evidence_span_ids": ["full_draft_ev_1"],
                        "decision_items": [],
                        "missing_source_classes": [],
                        "gap_items": [],
                    }
                    for section_id in section_ids
                ]
            },
        }
        if len(self.envelopes) == 2:
            result.pop("schema_version")
        return result


class TwiceRepairingFullDraftProvider(RepairingFullDraftProvider):
    def run(self, envelope: AiPromptEnvelope):
        if len(self.envelopes) < 2:
            self.envelopes.append(envelope)
            source = envelope.payload["allowed_sources"][0]
            section_id = envelope.payload["task_context"]["section_ids"][0]
            if len(self.envelopes) == 1:
                return {
                    "section_id": section_id,
                    "proposal_text": "正文过短",
                    "rationale": "不完整结构",
                    "evidence_span_ids": [],
                }
            return {
                "section_id": section_id,
                "proposal_text": "本研究将依照已确认的研究设计实施。" * 8,
                "rationale": "仍缺少完整外层合同。",
                "evidence_span_ids": ["full_draft_ev_1"],
            }
        return super().run(envelope)


class DiagnosticFailureProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"
    response_model = "deepseek-v4-pro"

    def run(self, envelope: AiPromptEnvelope):
        raise AiProviderRuntimeError(
            "provider_response_empty",
            diagnostics={
                "failure_code": "provider_response_empty",
                "wire_format": "json",
                "message_content_chars": 0,
                "message_reasoning_content_chars": 120,
            },
        )


class AiTaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.repo = DemoRepository(
            PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
        )
        self.source = AiTaskSourceRef(
            source_id="protocol_span_001",
            source_type="protocol_docx_span",
            title="研究方案 V2.1",
            locator="docx:p120",
            text_preview="随机前需完成禁限用药洗脱。",
            project_id="proj_mgk10_sar_demo",
            module="medical_monitoring",
        )
        self.request = AiTaskRequest(
            module="medical_monitoring",
            task_type="monitoring_risk_interpretation",
            prompt_version="monitoring_risk_interpretation_v0_1",
            allowed_sources=[self.source],
            user_instruction="请仅基于原始方案 span 解释医学监查风险。",
        )
        self.policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
        )
        self.test_only_policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
            test_only_provider_injection=True,
        )
        self.disabled_policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="disabled",
            model_name="not_configured",
        )

    def _synopsis_source(self, source_id: str, block: int, text: str):
        return self.source.model_copy(
            update={
                "source_id": source_id,
                "source_type": "project_protocol_synopsis",
                "locator": f"synopsis:test:upload:test:p1:b{block}",
                "text_preview": text,
                "project_id": "proj_synopsis_fidelity",
                "module": "medical_writing",
            }
        )

    @staticmethod
    def _synopsis_output(framing, picos, sources, field_evidence):
        return {
            "evidence_spans": [
                {
                    "span_id": f"ev_{source.source_id}",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": source.text_preview,
                }
                for source in sources
            ],
            "study_definition": {
                "framing": framing,
                "picos": picos,
                "field_evidence_span_ids": field_evidence,
            },
        }

    def test_single_source_consistency_candidates_use_safe_distinct_projection(self):
        source_text = (
            "这是一项拟在中国AD受试者中开展的确证性研究。研究对象包括：适合接受AD局部治疗，"
            "12 周岁及以上的青少年和成人（不限男女），AD皮损占全身体表面积的3 % ~ 20 %（不包括头皮），"
            "IGA评分为2 ~ 3。"
        )
        source = self.source.model_copy(update={"text_preview": source_text})
        candidate = {
            "proposal_text": source_text,
            "diff_patch": "无正文变更：保留原文",
            "rationale": "段内未发现冲突。",
            "evidence_span_ids": ["span_001"],
        }
        output = {"revision": {**candidate, "alternatives": [candidate, candidate]}}

        normalized = normalize_single_source_medical_writing_candidates(
            AiTaskType.MEDICAL_WRITING_REVISION,
            output,
            [source],
            {"revision_intent": "consistency_check", "candidate_count": 3},
        )

        candidates = [normalized["revision"], *normalized["revision"]["alternatives"]]
        self.assertEqual(3, len(candidates))
        self.assertEqual(
            3, len({item["proposal_text"].replace(" ", "") for item in candidates})
        )
        self.assertEqual(source_text, candidates[0]["proposal_text"])
        self.assertIn("12周岁", candidates[1]["proposal_text"])
        self.assertIn("3%～20%", candidates[1]["proposal_text"])
        self.assertIn("①适合接受AD局部治疗", candidates[2]["proposal_text"])
        self.assertTrue(
            all("单来源安全变体" in item["rationale"] for item in candidates)
        )

    def test_single_source_evidence_gap_projection_never_claims_external_support(self):
        source_text = (
            "研究对象包括：12 周岁及以上受试者，IGA评分为2 ~ 3，皮损面积为3 % ~ 20 %。"
        )
        source = self.source.model_copy(update={"text_preview": source_text})
        candidate = {
            "proposal_text": "基于方案设计，" + source_text,
            "diff_patch": "provider draft",
            "rationale": "缺少外部证据。",
            "evidence_span_ids": ["span_001"],
        }
        output = {"revision": {**candidate, "alternatives": []}}

        normalized = normalize_single_source_medical_writing_candidates(
            AiTaskType.MEDICAL_WRITING_REVISION,
            output,
            [source],
            {"revision_intent": "evidence_gap", "candidate_count": 4},
        )

        candidates = [normalized["revision"], *normalized["revision"]["alternatives"]]
        self.assertEqual(4, len(candidates))
        self.assertEqual(
            4, len({item["proposal_text"].replace(" ", "") for item in candidates})
        )
        self.assertTrue(all("基于" not in item["proposal_text"] for item in candidates))

    def test_safe_projection_does_not_run_when_external_evidence_is_present(self):
        output = {"revision": {"proposal_text": "provider output"}}
        second_source = self.source.model_copy(update={"source_id": "external_001"})
        self.assertIs(
            output,
            normalize_single_source_medical_writing_candidates(
                AiTaskType.MEDICAL_WRITING_REVISION,
                output,
                [self.source, second_source],
                {"revision_intent": "evidence_gap", "candidate_count": 4},
            ),
        )

    def test_blank_greenfield_anchor_cannot_become_evidence(self):
        blank_anchor = self.source.model_copy(
            update={
                "source_id": "blank_anchor",
                "source_type": "greenfield_working_copy_selection",
                "locator": "greenfield:section:synopsis:body:1",
                "text_preview": "",
            }
        )
        project_facts = self.source.model_copy(
            update={
                "source_id": "project_facts",
                "source_type": "current_project_study_definition",
                "locator": "study_definition:ra:revision:1",
                "text_preview": "试验药物：RA-01\n适应症：类风湿关节炎",
            }
        )
        output = {
            "input_source_ids": ["blank_anchor", "project_facts"],
            "evidence_spans": [
                {
                    "span_id": "blank_span",
                    "source_id": "blank_anchor",
                    "locator": blank_anchor.locator,
                    "quote": "",
                },
                {
                    "span_id": "fact_span",
                    "source_id": "project_facts",
                    "locator": project_facts.locator,
                    "quote": project_facts.text_preview,
                },
            ],
            "findings": [
                {
                    "finding_id": "blank_finding",
                    "source_id": "blank_anchor",
                    "evidence_span_ids": ["blank_span"],
                },
                {
                    "finding_id": "fact_finding",
                    "source_id": "project_facts",
                    "evidence_span_ids": ["blank_span", "fact_span"],
                },
            ],
            "revision": {
                "proposal_text": "RA-01用于类风湿关节炎研究。",
                "evidence_span_ids": ["blank_span", "fact_span"],
                "alternatives": [
                    {
                        "proposal_text": "本研究评价RA-01。",
                        "evidence_span_ids": ["blank_span"],
                    }
                ],
            },
        }

        normalized = strip_blank_greenfield_anchor_evidence(
            AiTaskType.MEDICAL_WRITING_REVISION,
            output,
            [blank_anchor, project_facts],
        )

        self.assertEqual(
            ["blank_anchor", "project_facts"],
            normalized["input_source_ids"],
        )
        self.assertEqual(
            ["fact_span"],
            [item["span_id"] for item in normalized["evidence_spans"]],
        )
        self.assertEqual(
            ["fact_finding"],
            [item["finding_id"] for item in normalized["findings"]],
        )
        self.assertEqual(
            ["fact_span"],
            normalized["findings"][0]["evidence_span_ids"],
        )
        self.assertEqual(
            ["fact_span"],
            normalized["revision"]["evidence_span_ids"],
        )
        self.assertEqual(
            [],
            normalized["revision"]["alternatives"][0]["evidence_span_ids"],
        )

    def test_nonempty_or_non_greenfield_sources_are_not_stripped(self):
        nonempty_greenfield = self.source.model_copy(
            update={
                "source_id": "greenfield_text",
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "已有正文。",
            }
        )
        empty_other = self.source.model_copy(
            update={
                "source_id": "empty_other",
                "source_type": "current_project_study_definition",
                "text_preview": "",
            }
        )
        output = {
            "findings": [
                {"finding_id": "finding", "evidence_span_ids": ["bad"]}
            ],
            "evidence_spans": [
                {
                    "span_id": "span_greenfield",
                    "source_id": "greenfield_text",
                    "locator": nonempty_greenfield.locator,
                    "quote": "已有正文。",
                },
                {
                    "span_id": "span_other",
                    "source_id": "empty_other",
                    "locator": empty_other.locator,
                    "quote": "",
                },
            ],
            "revision": {
                "proposal_text": "已有正文。",
                "evidence_span_ids": ["span_greenfield", "span_other"],
                "alternatives": [],
            },
        }

        self.assertIs(
            output,
            strip_blank_greenfield_anchor_evidence(
                AiTaskType.MEDICAL_WRITING_REVISION,
                output,
                [nonempty_greenfield, empty_other],
            ),
        )
        self.assertIs(
            output,
            strip_blank_greenfield_anchor_evidence(
                AiTaskType.REGULATORY_TRANSLATION_ZH,
                output,
                [
                    nonempty_greenfield.model_copy(
                        update={"text_preview": ""}
                    )
                ],
            ),
        )

    def test_full_draft_dangling_evidence_is_filtered_or_demoted_to_source_gap(self):
        output = {
            "evidence_spans": [
                {"span_id": "valid_span", "source_id": "project", "locator": "x", "quote": "依据"}
            ],
            "full_draft": {
                "sections": [
                    {
                        "section_id": "section_with_support",
                        "content_status": "complete",
                        "proposal_text": "有直接依据的完整正文。",
                        "rationale": "依据当前项目资料。",
                        "evidence_span_ids": ["missing_span", "valid_span"],
                        "decision_items": [],
                        "missing_source_classes": [],
                    },
                    {
                        "section_id": "section_without_support",
                        "content_status": "decision_required",
                        "proposal_text": "没有有效证据绑定的正文。",
                        "rationale": "原说明。",
                        "evidence_span_ids": ["missing_span"],
                        "decision_items": [{"question": "是否采用？"}],
                        "missing_source_classes": [],
                    },
                ]
            },
        }

        normalized = normalize_protocol_full_draft_evidence_ids(
            AiTaskType.PROTOCOL_FULL_DRAFT,
            output,
        )

        supported, unsupported = normalized["full_draft"]["sections"]
        self.assertEqual(["valid_span"], supported["evidence_span_ids"])
        self.assertEqual("complete", supported["content_status"])
        self.assertEqual("source_gap", unsupported["content_status"])
        self.assertEqual("", unsupported["proposal_text"])
        self.assertEqual([], unsupported["decision_items"])
        self.assertEqual([], unsupported["evidence_span_ids"])
        self.assertEqual(
            ["支持本章节正文的当前项目直接来源"],
            unsupported["missing_source_classes"],
        )

    def test_full_draft_normalizer_clears_gap_evidence_and_demotes_unsupported_rule(self):
        source = self.source.model_copy(
            update={
                "source_id": "project",
                "locator": "loc",
                "text_preview": "本研究采用双盲设计。",
            }
        )
        output = {
            "findings": [
                {"finding_id": "finding", "evidence_span_ids": ["bad"]}
            ],
            "evidence_spans": [
                {"span_id": "valid", "source_id": "project", "locator": "loc", "quote": "双盲设计"},
                {"span_id": "bad", "source_id": "project", "locator": "loc", "quote": "来源中不存在"},
            ],
            "full_draft": {"sections": [
                {
                    "section_id": "unsupported",
                    "content_status": "complete",
                    "proposal_text": "发生紧急情况时必须立即揭盲，并记录原因。",
                    "rationale": "具体揭盲程序尚未明确，需确认。",
                    "evidence_span_ids": ["valid"],
                    "decision_items": [],
                    "missing_source_classes": [],
                },
                {
                    "section_id": "supported_partial",
                    "content_status": "complete",
                    "proposal_text": "本研究采用双盲设计并使用匹配安慰剂；揭盲流程应在项目文件中明确。",
                    "rationale": "双盲设计已有项目事实支持，具体揭盲程序尚未明确，需确认。",
                    "evidence_span_ids": ["valid"],
                    "decision_items": [],
                    "missing_source_classes": [],
                },
                {
                    "section_id": "unsupported_schedule",
                    "content_status": "complete",
                    "proposal_text": "生命体征和12导联心电图评估安排在筛选期、基线/第1天和第2、4、8、12、16周。",
                    "rationale": "具体安全性评估时点未提供，需确认。",
                    "evidence_span_ids": ["valid"],
                    "decision_items": [],
                    "missing_source_classes": [],
                },
                {
                    "section_id": "gap",
                    "content_status": "source_gap",
                    "proposal_text": "不应保留的填充文字",
                    "rationale": "缺少研究者手册。",
                    "evidence_span_ids": ["bad"],
                    "decision_items": [],
                    "missing_source_classes": ["研究者手册"],
                },
            ]},
        }
        normalized = normalize_protocol_full_draft_evidence_ids(
            AiTaskType.PROTOCOL_FULL_DRAFT,
            output,
            [source],
        )
        unsupported, supported_partial, unsupported_schedule, gap = normalized["full_draft"]["sections"]
        self.assertEqual("source_gap", unsupported["content_status"])
        self.assertEqual("", unsupported["proposal_text"])
        self.assertEqual([], unsupported["evidence_span_ids"])
        self.assertEqual("complete", supported_partial["content_status"])
        self.assertEqual(["valid"], supported_partial["evidence_span_ids"])
        self.assertIn("本研究采用双盲设计", supported_partial["proposal_text"])
        self.assertEqual("source_gap", unsupported_schedule["content_status"])
        self.assertEqual("", unsupported_schedule["proposal_text"])
        self.assertEqual("source_gap", gap["content_status"])
        self.assertEqual("", gap["proposal_text"])
        self.assertEqual([], gap["evidence_span_ids"])
        self.assertEqual(["valid"], [item["span_id"] for item in normalized["evidence_spans"]])
        self.assertEqual([], normalized["findings"][0]["evidence_span_ids"])

    def test_revision_semantic_gate_rejects_ai_only_objective_and_endpoint_upgrades(
        self,
    ):
        source = self.source.model_copy(
            update={
                "source_type": "protocol_docx_paragraph_selection",
                "text_preview": "评价研究药物治疗目标适应症的有效性。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "主要目的：评价研究药物治疗目标适应症的有效性。",
                "alternatives": [
                    {"proposal_text": "主要终点为预设时间点较基线的变化。"},
                ],
            }
        }

        errors = validate_medical_writing_revision_semantics(output, [source])

        self.assertTrue(any("objective.primary" in error for error in errors))
        self.assertTrue(any("endpoint.primary" in error for error in errors))

    def test_revision_semantic_gate_ignores_company_corpus_as_project_fact_support(
        self,
    ):
        current_source = self.source.model_copy(
            update={
                "source_type": "protocol_docx_paragraph_selection",
                "text_preview": "评价研究药物治疗目标适应症的有效性。",
            }
        )
        corpus_source = self.source.model_copy(
            update={
                "source_id": "company_corpus_001",
                "source_type": "company_protocol_reference_corpus",
                "text_preview": "主要目的为评价某历史研究药物的有效性。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "本研究主要目的为评价研究药物治疗目标适应症的有效性。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [current_source, corpus_source],
        )

        self.assertTrue(any("objective.primary" in error for error in errors))

    def test_revision_semantic_gate_ignores_shared_phase1_corpus_as_project_fact_support(
        self,
    ):
        current_source = self.source.model_copy(
            update={
                "source_type": "protocol_docx_paragraph_selection",
                "text_preview": "评价研究药物治疗目标适应症的有效性。",
            }
        )
        shared_source = self.source.model_copy(
            update={
                "source_id": "shared_phase1_001",
                "source_type": "shared_phase1_protocol_reference_corpus",
                "text_preview": "主要目的为评价竞品研究药物的有效性。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "本研究主要目的为评价研究药物治疗目标适应症的有效性。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [current_source, shared_source],
        )

        self.assertTrue(any("objective.primary" in error for error in errors))

    def test_revision_semantic_gate_allows_labels_already_supported_by_project_source(
        self,
    ):
        source = self.source.model_copy(
            update={
                "source_type": "protocol_docx_paragraph_selection",
                "text_preview": "主要试验目的：评价研究药物的有效性；主要终点为预设时间点较基线的变化。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "主要目的为评价研究药物的有效性。",
                "alternatives": [
                    {"proposal_text": "主要终点为预设时间点较基线的变化。"},
                ],
            }
        }

        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(output, [source]),
        )

    def test_revision_semantic_gate_treats_exploratory_wording_as_equivalent(self):
        source = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "这是一项开放标签、单臂、多中心、剂量递增的早期患者探索研究。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "本研究为开放标签、单臂、多中心、剂量递增的早期患者探索性研究。",
                "alternatives": [],
            }
        }

        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(output, [source]),
        )

    def test_revision_semantic_gate_treats_dose_exploration_as_exploratory_support(
        self,
    ):
        source = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "本研究为多中心、随机、开放标签、平行、剂量探索；分为低剂量组和高剂量组。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "本研究为多中心、随机、开放标签、平行分组的剂量探索性临床研究。",
                "alternatives": [],
            }
        }

        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(output, [source]),
        )

    def test_revision_semantic_gate_rejects_population_and_commitment_drift(self):
        source = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "纳入中重度活动性类风湿关节炎成人试验参与者，接受研究药物皮下注射。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "计划纳入中重度活动性类风湿关节炎成人患者，受试者将接受研究药物皮下注射。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(output, [source])

        self.assertTrue(any("status.planned" in error for error in errors))
        self.assertTrue(any("status.future_commitment" in error for error in errors))
        self.assertTrue(any("introduces population terms" in error for error in errors))
        self.assertTrue(
            any("omits controlled population terms" in error for error in errors)
        )

    def test_revision_semantic_gate_allows_blank_greenfield_draft_population_from_approved_evidence(
        self,
    ):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_competitor_eligibility_001",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "受试者应为18至75岁，并符合Hanifin和Rajka特应性皮炎诊断标准。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "受试者应为18至75岁，并符合Hanifin和Rajka特应性皮炎诊断标准。",
                "alternatives": [],
            }
        }

        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(
                output,
                [blank_target, approved_evidence],
            ),
        )

        omission_is_allowed = {
            "revision": {
                "proposal_text": "年龄应为18至75岁，并符合Hanifin和Rajka特应性皮炎诊断标准。",
                "alternatives": [],
            }
        }
        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(
                omission_is_allowed,
                [blank_target, approved_evidence],
            ),
        )

        unsupported_population = {
            "revision": {
                "proposal_text": "健康志愿者应为18至75岁。",
                "alternatives": [],
            }
        }
        self.assertTrue(
            any(
                "introduces population terms" in error
                for error in validate_medical_writing_revision_semantics(
                    unsupported_population,
                    [blank_target, approved_evidence],
                )
            )
        )

        unresolved_placeholder = {
            "revision": {
                "proposal_text": "受试者年龄和疾病严重度阈值由方案规定。",
                "alternatives": [],
            }
        }
        self.assertTrue(
            any(
                "unresolved blank-draft placeholders" in error
                for error in validate_medical_writing_revision_semantics(
                    unresolved_placeholder,
                    [blank_target, approved_evidence],
                )
            )
        )

        unsupported_regulatory_decoration = {
            "revision": {
                "proposal_text": (
                    "受试者应为18至75岁，并符合Hanifin和Rajka特应性皮炎诊断标准；"
                    "筛选前须签署经伦理委员会批准的知情同意书，"
                    "疾病严重度由经认证研究者进行评估。"
                ),
                "alternatives": [],
            }
        }
        decoration_errors = validate_medical_writing_revision_semantics(
            unsupported_regulatory_decoration,
            [blank_target, approved_evidence],
        )
        self.assertTrue(
            any("consent.ethics_approved" in error for error in decoration_errors)
        )
        self.assertTrue(
            any("investigator.certified" in error for error in decoration_errors)
        )

        supported_regulatory_detail = approved_evidence.model_copy(
            update={
                "text_preview": (
                    "受试者应为18至75岁，并符合Hanifin和Rajka特应性皮炎诊断标准；"
                    "签署经伦理委员会批准的知情同意书后，由经认证研究者进行评估。"
                ),
            }
        )
        self.assertEqual(
            [],
            validate_medical_writing_revision_semantics(
                unsupported_regulatory_decoration,
                [blank_target, supported_regulatory_detail],
            ),
        )

    def test_revision_semantic_gate_rejects_superiority_upgrade(self):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_objective",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "比较4种给药方案与安慰剂在中重度特应性皮炎受试者中的疗效。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "验证4种给药方案的疗效是否优于安慰剂。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, approved_evidence],
        )

        self.assertTrue(any("comparison.superiority" in error for error in errors))

    def test_revision_semantic_gate_rejects_changed_or_omitted_roman_level_ranges(self):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_tcs_ranges",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "中强效TCS为欧盟II至IV级，美国I至V级。",
            }
        )
        project_region = self.source.model_copy(
            update={
                "source_id": "project_region",
                "source_type": "project_fact",
                "text_preview": "本研究包含欧盟和美国研究中心。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "中强效TCS为欧盟III至IV级。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, project_region, approved_evidence],
        )

        self.assertTrue(any("omits source Roman-numeral" in error for error in errors))
        self.assertTrue(
            any("changes or invents Roman-numeral" in error for error in errors)
        )

    def test_revision_semantic_gate_preserves_last_dose_timing_anchor(self):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_contraception",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "整个试验期间以及末次使用研究药物后至少18周内采用高效避孕。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "研究期间及研究结束后18周内采用高效避孕。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, approved_evidence],
        )

        self.assertTrue(any("timing.study_end" in error for error in errors))
        self.assertTrue(
            any("omits required source timing" in error for error in errors)
        )

    def test_revision_semantic_gate_rejects_duration_bound_reversal(self):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_tcs_duration",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": (
                    "规律使用TCS至少28天，或达到产品说明书规定的最长用药时长"
                    "（例如超强效TCS为14天），以较短者为准。"
                ),
            }
        )
        output = {
            "revision": {
                "proposal_text": "规律使用TCS至少28天；超强效TCS至少14天。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, approved_evidence],
        )

        self.assertTrue(
            any("reverses numeric bound directions" in error for error in errors)
        )

    def test_revision_semantic_gate_rejects_competitor_region_and_cross_references(
        self,
    ):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_regional_evidence",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "有关日本地区的特殊要求，请参见第12.5.4节。",
            }
        )
        output = {
            "revision": {
                "proposal_text": "有关日本地区的特殊要求，请参见第12.5.4节。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, approved_evidence],
        )

        self.assertTrue(any("non-China regional clauses" in error for error in errors))
        self.assertTrue(
            any("competitor protocol cross-references" in error for error in errors)
        )

    def test_revision_semantic_gate_does_not_turn_china_region_into_population_identity(
        self,
    ):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        project_definition = self.source.model_copy(
            update={
                "source_id": "current_study_definition",
                "source_type": "current_project_study_definition",
                "text_preview": (
                    "试验药物：AD-01\n"
                    "适应症：特应性皮炎\n"
                    "开发区域：中国\n"
                    "目标研究人群：特应性皮炎成人试验参与者"
                ),
            }
        )
        output = {
            "revision": {
                "proposal_text": "评价AD-01在中国特应性皮炎成人受试者中的疗效。",
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, project_definition],
        )

        self.assertTrue(
            any(
                "participant nationality or population attribute" in error
                for error in errors
            )
        )

    def test_revision_semantic_gate_rejects_severity_scale_and_contraception_drift(
        self,
    ):
        blank_target = self.source.model_copy(
            update={
                "source_type": "greenfield_working_copy_selection",
                "text_preview": "",
            }
        )
        approved_evidence = self.source.model_copy(
            update={
                "source_id": "approved_inclusion_evidence",
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": (
                    "存在重要的副作用时不适合治疗。IGA 0至2分表示低活动状态。"
                    "高效避孕方法包括一贯禁欲、同性伴侣关系或已行输精管结扎"
                    "且保持单一性伴侣关系。"
                ),
            }
        )
        output = {
            "revision": {
                "proposal_text": (
                    "存在严重副作用时不适合治疗。EASI相当于IGA 0至2分。"
                    "高效避孕方法包括一贯禁欲（同性伴侣关系或已行输精管结扎"
                    "的单一性伴侣）。"
                ),
                "alternatives": [],
            }
        }

        errors = validate_medical_writing_revision_semantics(
            output,
            [blank_target, approved_evidence],
        )

        self.assertTrue(any("upgrades 重要的副作用" in error for error in errors))
        self.assertTrue(any("EASI/IGA equivalence" in error for error in errors))
        self.assertTrue(
            any(
                "incorrectly groups distinct contraception" in error for error in errors
            )
        )

    def test_medical_writing_long_reference_accepts_only_contiguous_verbatim_quote(
        self,
    ):
        source = self.source.model_copy(
            update={
                "source_type": "approved_competitor_protocol_evidence",
                "text_preview": "受试者应符合下列全部入选标准：年龄为18至75岁，且已签署知情同意书。",
            }
        )

        self.assertTrue(
            evidence_quote_matches_source(
                AiTaskType.MEDICAL_WRITING_REVISION,
                source,
                "年龄为18至75岁",
            )
        )
        self.assertFalse(
            evidence_quote_matches_source(
                AiTaskType.MEDICAL_WRITING_REVISION,
                source,
                "年龄18～75岁",
            )
        )
        self.assertFalse(
            evidence_quote_matches_source(
                AiTaskType.REGULATORY_TRANSLATION_ZH,
                source,
                "年龄为18至75岁",
            )
        )
        project_definition = source.model_copy(
            update={
                "source_type": "current_project_study_definition",
                "text_preview": ("试验药物：AD-01\n适应症：特应性皮炎\n开发区域：中国"),
            }
        )
        self.assertTrue(
            evidence_quote_matches_source(
                AiTaskType.MEDICAL_WRITING_REVISION,
                project_definition,
                "试验药物：AD-01",
            )
        )
        self.assertFalse(
            evidence_quote_matches_source(
                AiTaskType.MEDICAL_WRITING_REVISION,
                project_definition,
                "试验药物：AD01",
            )
        )

    def test_disabled_external_provider_records_blocked_run_not_codex_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: DisabledAiProvider(),
                policy_resolver=self.disabled_policy,
            )

            run = runner.submit_internal("proj_mgk10_sar_demo", self.request)

            self.assertEqual(AiTaskRunStatus.BLOCKED, run.status)
            self.assertFalse(run.codex_runtime_dependency)
            self.assertEqual("not_configured", run.ai_gateway_status)
            self.assertIn("not configured", run.error_message)
            self.assertEqual(
                [run.run_id],
                [item.run_id for item in runner.list_runs("proj_mgk10_sar_demo")],
            )

    def test_configured_provider_output_is_validated_persisted_and_evidence_indexed(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: FakeProvider(),
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_mgk10_sar_demo", self.request)

            self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
            self.assertEqual("passed", run.output_validation_status)
            self.assertEqual("buddy", run.provider)
            self.assertFalse(run.codex_runtime_dependency)
            self.assertEqual(1, len(run.artifacts))
            self.assertEqual("finding_001", run.evidence_entries[0].finding_ids[0])
            restored = runner.get("proj_mgk10_sar_demo", run.run_id)
            self.assertEqual(run.run_id, restored.run_id)

    def test_provider_output_with_unrequested_source_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: ExtraSourceProvider(),
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_mgk10_sar_demo", self.request)

            self.assertEqual(AiTaskRunStatus.FAILED, run.status)
            self.assertTrue(
                any(
                    "unrequested input_source_ids" in error
                    for error in run.validation_errors
                )
            )

    def test_full_draft_invalid_evidence_is_deterministically_demoted_without_retry(self):
        source = self.source.model_copy(
            update={
                "source_id": "full_draft_packet",
                "source_type": "protocol_full_draft_selection",
                "text_preview": "本研究为随机、双盲、安慰剂对照的III期临床研究。",
                "project_id": "proj_full_draft",
                "module": "medical_writing",
            }
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_full_draft",
            prompt_version="protocol_full_draft_v0_11",
            allowed_sources=[source],
            user_instruction="生成完整章节正文。",
            task_context={
                "draft_version": "a" * 64,
                "section_ids": ["section_1"],
                "marker_open": "SECTION_ID=",
                "marker_close": "\n",
                "minimum_body_chars": 80,
                "decision_fact_paths": ["design.blinding"],
            },
        )
        provider = RepairingFullDraftProvider()
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_full_draft", request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status, run.validation_errors)
        self.assertEqual(1, len(provider.envelopes))
        self.assertEqual(
            [65_536],
            [item.max_output_tokens for item in provider.envelopes],
        )
        output = run.artifacts[-1].payload
        section = output["full_draft"]["sections"][0]
        self.assertEqual("source_gap", section["content_status"])
        self.assertEqual("", section["proposal_text"])
        self.assertEqual([], section["evidence_span_ids"])

    def test_full_draft_allows_one_final_same_model_structural_correction(self):
        source = self.source.model_copy(
            update={
                "source_id": "full_draft_packet",
                "source_type": "protocol_full_draft_selection",
                "text_preview": "本研究为随机、双盲、安慰剂对照的III期临床研究。",
                "project_id": "proj_full_draft",
                "module": "medical_writing",
            }
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_full_draft",
            prompt_version="protocol_full_draft_v0_11",
            allowed_sources=[source],
            user_instruction="生成完整章节正文。",
            task_context={
                "draft_version": "a" * 64,
                "section_ids": ["section_1"],
                "marker_open": "SECTION_ID=",
                "marker_close": "\n",
                "minimum_body_chars": 80,
                "decision_fact_paths": ["design.blinding"],
            },
        )
        provider = TwiceRepairingFullDraftProvider()
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_full_draft", request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status, run.validation_errors)
        self.assertEqual(3, len(provider.envelopes))
        self.assertEqual(2, provider.envelopes[2].payload["repair_context"]["repair_attempt"])

    def test_provider_failure_persists_only_safe_response_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: DiagnosticFailureProvider(),
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_mgk10_sar_demo", self.request)

        self.assertEqual(AiTaskRunStatus.FAILED, run.status)
        self.assertEqual(1, len(run.artifacts))
        diagnostics = run.artifacts[0].payload["diagnostics"]
        self.assertEqual("provider_response_empty", diagnostics["failure_code"])
        self.assertEqual(0, diagnostics["message_content_chars"])
        self.assertEqual(120, diagnostics["message_reasoning_content_chars"])
        self.assertNotIn("response_body", diagnostics)

    def test_source_free_non_default_synopsis_field_is_reset_to_default_and_marked_missing(
        self,
    ):
        output = {
            "findings": [],
            "uncertainties": [],
            "study_definition": {
                "framing": MedicalWritingStudyFraming().model_dump(mode="json"),
                "picos": {
                    **MedicalWritingPicosDefinition().model_dump(mode="json"),
                    "primary_endpoint": "第8周达到PASI 75应答的受试者比例",
                    "prohibited_concomitant_rules": ["禁止使用生物制剂"],
                },
                "synopsis_text": "银屑病研究方案摘要",
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {
                    "picos.primary_endpoint": ["ev_primary"],
                },
            },
        }

        normalized = normalize_protocol_synopsis_missing_findings(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            output,
        )

        picos = normalized["study_definition"]["picos"]
        self.assertEqual("第8周达到PASI 75应答的受试者比例", picos["primary_endpoint"])
        self.assertEqual([], picos["prohibited_concomitant_rules"])
        self.assertIn(
            "picos.prohibited_concomitant_rules",
            normalized["study_definition"]["missing_fields"],
        )

    def test_protocol_synopsis_invalid_quote_requires_one_ai_repair(self):
        source = self.source.model_copy(
            update={
                "source_id": "synopsis_chunk_1",
                "source_type": "project_protocol_synopsis",
                "locator": "synopsis:source_1:docx:paragraph:2",
                "text_preview": "本研究为类风湿关节炎II期随机双盲安慰剂对照研究。",
                "project_id": "proj_ra",
                "module": "medical_writing",
            }
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_synopsis_structuring",
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=[source],
            user_instruction="仅基于方案摘要原文提取研究定义候选。",
        )
        provider = RepairingSynopsisProvider()
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_ra", request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
        self.assertEqual(2, len(provider.envelopes))
        self.assertEqual(2, len(run.artifacts))
        self.assertTrue(run.artifacts[0].validation_errors)
        self.assertEqual([], run.artifacts[-1].validation_errors)
        self.assertEqual(
            source.text_preview,
            run.artifacts[-1].payload["evidence_spans"][0]["quote"],
        )

    def test_protocol_synopsis_repair_still_fails_closed_after_one_retry(self):
        source = self.source.model_copy(
            update={
                "source_id": "synopsis_chunk_1",
                "source_type": "project_protocol_synopsis",
                "locator": "synopsis:source_1:docx:paragraph:2",
                "text_preview": "本研究为类风湿关节炎II期随机双盲安慰剂对照研究。",
                "project_id": "proj_ra",
                "module": "medical_writing",
            }
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_synopsis_structuring",
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=[source],
            user_instruction="仅基于方案摘要原文提取研究定义候选。",
        )
        provider = RepairingSynopsisProvider(always_invalid_locator=True)
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=self.test_only_policy,
            )

            run = runner.submit_internal("proj_ra", request)

        self.assertEqual(AiTaskRunStatus.FAILED, run.status)
        self.assertEqual(2, len(provider.envelopes))
        self.assertEqual(2, len(run.artifacts))
        self.assertTrue(
            any("evidence locator mismatch" in error for error in run.validation_errors)
        )

    def test_d017_fidelity_rejects_compressed_objectives_and_transfusion_definition(
        self,
    ):
        primary_objective = (
            "探索CMS-D017胶囊在既往未接受过补体抑制剂治疗、存在活动性溶血的PNH成人患者中的有效性，"
            "评价不同剂量水平连续治疗12周后对贫血改善的作用，并为后续确证性研究的推荐剂量和"
            "主要疗效终点设置提供依据。"
        )
        secondary_objectives = (
            "评价CMS-D017胶囊不同剂量水平对Hb应答、Hb正常化、血管内溶血控制、红细胞生成负荷、"
            "胆红素代谢、输血需求、疲乏症状及PNH克隆相关指标的影响；\n"
            "评价CMS-D017胶囊在PNH患者中的安全性和耐受性。"
        )
        transfusion_endpoint = (
            "治疗D14、D28、D56、D84时，Hb较基线增加≥20 g/L且D14至相应访视未输注红细胞且"
            "未达输血标准的参与者比例（注：输血标准定义为血红蛋白水平≤90 g/L且出现需输血治疗的"
            "严重体征和/或症状；或血红蛋白≤70 g/L，无论是否存在相关临床体征和/或症状。）"
        )
        sources = [
            self._synopsis_source("d017_b13", 13, "目的与估计目标/终点\t主要目的\t相应的研究终点"),
            self._synopsis_source(
                "d017_b14",
                14,
                f"{primary_objective}\t主要有效性终点：\n治疗D84时血红蛋白（Hb）水平较基线的变化值（g/L)。",
            ),
            self._synopsis_source("d017_b15", 15, "次要目的\t相应的研究终点"),
            self._synopsis_source(
                "d017_b16",
                16,
                f"{secondary_objectives}\t次要有效性终点：\n{transfusion_endpoint}\n"
                "安全性终点：\n1）不良事件（AE）、严重不良事件（SAE）和特别关注的不良事件（AESI）。",
            ),
        ]
        framing = MedicalWritingStudyFraming().model_dump(mode="json")
        picos = MedicalWritingPicosDefinition().model_dump(mode="json")
        picos["primary_objectives"] = [
            "评价CMS-D017在既往未接受过补体抑制剂治疗的、存在活动性溶血的成人PNH患者中的有效性。",
        ]
        picos["secondary_objectives"] = [
            "评价CMS-D017在PNH患者中的有效性和安全性。",
        ]
        picos["primary_endpoint"] = "治疗D84时Hb较基线的变化值"
        picos["other_secondary_endpoints"] = [
            "治疗D14、D28、D56、D84时Hb较基线增加≥20 g/L的参与者比例"
        ]
        picos["safety_endpoints"] = ["AE、SAE和AESI"]

        errors = validate_protocol_synopsis_source_fidelity(
            self._synopsis_output(
                framing,
                picos,
                sources,
                {
                    "picos.primary_objectives": ["ev_d017_b14"],
                    "picos.secondary_objectives": ["ev_d017_b16"],
                    "picos.primary_endpoint": ["ev_d017_b14"],
                    "picos.other_secondary_endpoints": ["ev_d017_b16"],
                    "picos.safety_endpoints": ["ev_d017_b16"],
                },
            ),
            sources,
        )

        self.assertTrue(any("picos.primary_objectives" in error for error in errors))
        self.assertTrue(any("picos.secondary_objectives" in error for error in errors))
        self.assertTrue(any("picos.primary_endpoint" in error for error in errors))
        self.assertTrue(any("picos.other_secondary_endpoints" in error for error in errors))
        self.assertTrue(any("one-to-one" in error or "lost qualifiers" in error for error in errors))

    def test_d017_fidelity_accepts_complete_main_objective_and_endpoint(self):
        objective = (
            "探索CMS-D017胶囊在既往未接受过补体抑制剂治疗、存在活动性溶血的PNH成人患者中的有效性，"
            "评价不同剂量水平连续治疗12周后对贫血改善的作用，并为后续确证性研究的推荐剂量和"
            "主要疗效终点设置提供依据。"
        )
        endpoint = "治疗D84时血红蛋白（Hb）水平较基线的变化值（g/L)。"
        header = self._synopsis_source(
            "d017_header", 13, "目的与估计目标/终点\t主要目的\t相应的研究终点"
        )
        row = self._synopsis_source(
            "d017_main", 14, f"{objective}\t主要有效性终点：\n{endpoint}"
        )
        picos = MedicalWritingPicosDefinition().model_dump(mode="json")
        picos["primary_objectives"] = [objective]
        picos["primary_endpoint"] = endpoint
        output = self._synopsis_output(
            MedicalWritingStudyFraming().model_dump(mode="json"),
            picos,
            [header, row],
            {
                "picos.primary_objectives": ["ev_d017_main"],
                "picos.primary_endpoint": ["ev_d017_main"],
            },
        )

        self.assertEqual(
            [], validate_protocol_synopsis_source_fidelity(output, [header, row])
        )

    def test_d017_fidelity_accepts_secondary_objective_items_and_full_transfusion_rule(
        self,
    ):
        objective_1 = (
            "评价CMS-D017胶囊不同剂量水平对Hb应答、Hb正常化、血管内溶血控制、红细胞生成负荷、"
            "胆红素代谢、输血需求、疲乏症状及PNH克隆相关指标的影响；"
        )
        objective_2 = "评价CMS-D017胶囊在PNH患者中的安全性和耐受性。"
        endpoint = (
            "治疗D14、D28、D56、D84时，Hb较基线增加≥20 g/L且D14至相应访视未输注红细胞且"
            "未达输血标准的参与者比例（注：输血标准定义为血红蛋白水平≤90 g/L且出现需输血治疗的"
            "严重体征和/或症状；或血红蛋白≤70 g/L，无论是否存在相关临床体征和/或症状。）"
        )
        header = self._synopsis_source("d017_secondary_header", 15, "次要目的\t相应的研究终点")
        row = self._synopsis_source(
            "d017_secondary",
            16,
            f"{objective_1}\n{objective_2}\t次要有效性终点：\n{endpoint}",
        )
        picos = MedicalWritingPicosDefinition().model_dump(mode="json")
        picos["secondary_objectives"] = [objective_1, objective_2]
        picos["other_secondary_endpoints"] = [endpoint]
        output = self._synopsis_output(
            MedicalWritingStudyFraming().model_dump(mode="json"),
            picos,
            [header, row],
            {
                "picos.secondary_objectives": ["ev_d017_secondary"],
                "picos.other_secondary_endpoints": ["ev_d017_secondary"],
            },
        )

        self.assertEqual(
            [], validate_protocol_synopsis_source_fidelity(output, [header, row])
        )

    def test_my004_fidelity_rejects_merged_and_reordered_objectives(self):
        source = self._synopsis_source(
            "my004_b26",
            26,
            "研究目的\t主要目的：\n评估MY004567片在中至重度活动性类风湿关节炎患者中的有效性。\n"
            "次要目的：\n评估MY004567片在中至重度活动性类风湿关节炎患者中的安全性和耐受性。\n"
            "评估MY004567片在中至重度活动性类风湿关节炎患者中的药代动力学（PK）特征。\n"
            "探索性目的：\n探索MY004567片在中至重度活动性类风湿关节炎患者中的药效学（PD）特征。",
        )
        picos = MedicalWritingPicosDefinition().model_dump(mode="json")
        picos["primary_objectives"] = [
            "评估MY004567片的有效性、安全性和耐受性。",
        ]
        picos["secondary_objectives"] = [
            "探索MY004567片的PD特征。",
        ]
        output = self._synopsis_output(
            MedicalWritingStudyFraming().model_dump(mode="json"),
            picos,
            [source],
            {
                "picos.primary_objectives": ["ev_my004_b26"],
                "picos.secondary_objectives": ["ev_my004_b26"],
            },
        )

        errors = validate_protocol_synopsis_source_fidelity(output, [source])

        self.assertTrue(any("picos.primary_objectives" in error for error in errors))
        self.assertTrue(any("picos.secondary_objectives" in error for error in errors))
        self.assertTrue(any("picos.exploratory_objectives" in error for error in errors))
        self.assertTrue(any("my004_b26" in error for error in errors))

    def test_non_anchor_structured_fields_may_normalize_wording_when_source_bound(self):
        source = self._synopsis_source(
            "d017_washout",
            29,
            "既往接受过补体抑制剂治疗的参与者，应在筛选前完成方案规定的洗脱期。",
        )
        picos = MedicalWritingPicosDefinition().model_dump(mode="json")
        picos["washout_rules"] = ["既往补体抑制剂须在筛选前完成方案规定的洗脱期"]
        output = self._synopsis_output(
            MedicalWritingStudyFraming().model_dump(mode="json"),
            picos,
            [source],
            {"picos.washout_rules": ["ev_d017_washout"]},
        )

        self.assertEqual(
            [], validate_protocol_synopsis_source_fidelity(output, [source])
        )

    def test_trusted_internal_request_records_blocked_run_when_provider_env_is_missing(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                self.repo,
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: DisabledAiProvider(),
                policy_resolver=self.disabled_policy,
            )
            run = runner.submit_internal("proj_mgk10_sar_demo", self.request)

        self.assertEqual("blocked", run.status)
        self.assertFalse(run.codex_runtime_dependency)
        self.assertEqual("not_configured", run.ai_gateway_status)

    def test_policy_rejects_unsupported_task_type_before_provider_call(self):
        provider = FakeProvider()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(Path(tempfile.gettempdir()) / "unused_ai_runs.jsonl"),
            provider_factory=lambda resolution: provider,
            policy_resolver=self.policy,
        )
        request = self.request.model_copy(update={"task_type": "not_a_real_task"})
        with self.assertRaisesRegex(ValueError, "unsupported AI task_type"):
            runner.submit_internal("proj_mgk10_sar_demo", request)


if __name__ == "__main__":
    unittest.main()
