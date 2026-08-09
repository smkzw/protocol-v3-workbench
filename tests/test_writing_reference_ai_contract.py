from __future__ import annotations

import unittest
from types import SimpleNamespace

from packages.contracts.workbench_contracts import AiTaskRequest, AiTaskSourceRef
from services.api.app.ai_execution_policy import AiExecutionPolicyDenied, AiExecutionPolicyResolver
from services.api.app.ai_gateway import (
    AiSourceRef,
    AiTaskSpec,
    AiTaskType,
    PromptRegistry,
    validate_ai_output,
)
from services.api.app.ai_task_runner import (
    AiTaskRunner,
    bind_exact_source_quotes,
    bind_protocol_synopsis_source_quotes,
    normalize_protocol_synopsis_missing_findings,
)


def translation_output() -> dict:
    return {
        "task_id": "translation_001",
        "task_type": "regulatory_translation_zh",
        "provider": "openai_compatible",
        "model": "configured-model",
        "prompt_version": "regulatory_translation_zh_v0_5",
        "input_source_ids": ["wref_span_001"],
        "forbidden_source_ids": [],
        "findings": [
            {
                "finding_id": "finding_translation_001",
                "status": "needs_medical_confirmation",
                "title": "监管中文候选译文",
                "source_id": "wref_span_001",
                "evidence_span_ids": ["evidence_translation_001"],
            }
        ],
        "evidence_spans": [
            {
                "span_id": "evidence_translation_001",
                "source_id": "wref_span_001",
                "locator": "ctgov:NCT05014438:Prot_SAP_000.pdf:p12:b4",
                "quote": "Participants must not receive SCS within 14 days.",
            }
        ],
        "uncertainties": [
            {"level": "medical_review", "description": "候选译文待医学经理确认。"}
        ],
        "needs_medical_confirmation": True,
        "schema_version": "ai_task_output_v0_1",
        "translation": {
            "translated_text": "受试者在14天内不得接受SCS。",
            "glossary_version": "cms_regulatory_zh_v1",
            "rationale": "保留缩写、时间窗和否定含义。",
            "evidence_span_ids": ["evidence_translation_001"],
        },
    }


class WritingReferenceAiContractTests(unittest.TestCase):
    def test_synopsis_quote_binding_restores_exact_source_after_layout_normalization(self):
        source = SimpleNamespace(
            source_id="synopsis_chunk_1",
            locator="docx:paragraph:12",
            text_preview="本研究为II期、随机、双盲（安慰剂对照）研究。\n主要终点见第12周。",
        )
        output = {
            "evidence_spans": [
                {
                    "span_id": "ev_1",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": "本研究为II期,随机,双盲(安慰剂对照)研究。主要终点见第12周。",
                }
            ]
        }

        bound = bind_protocol_synopsis_source_quotes(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING, output, [source]
        )

        self.assertEqual(source.text_preview, bound["evidence_spans"][0]["quote"])

    def test_synopsis_quote_binding_keeps_unmatched_quote_for_strict_rejection(self):
        source = SimpleNamespace(
            source_id="synopsis_chunk_1",
            locator="docx:paragraph:12",
            text_preview="本研究为II期随机双盲研究。",
        )
        output = {
            "evidence_spans": [
                {
                    "span_id": "ev_1",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": "本研究为III期随机双盲研究。",
                }
            ]
        }

        bound = bind_protocol_synopsis_source_quotes(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING, output, [source]
        )

        self.assertEqual(
            "本研究为III期随机双盲研究。",
            bound["evidence_spans"][0]["quote"],
        )

    def test_synopsis_quote_binding_does_not_rebind_a_mismatched_locator(self):
        source = SimpleNamespace(
            source_id="synopsis_chunk_1",
            locator="docx:paragraph:12",
            text_preview="本研究为II期随机双盲研究。",
        )
        output = {
            "evidence_spans": [
                {
                    "span_id": "ev_1",
                    "source_id": source.source_id,
                    "locator": "docx:paragraph:99",
                    "quote": "本研究为III期随机双盲研究。",
                }
            ]
        }

        bound = bind_protocol_synopsis_source_quotes(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING, output, [source]
        )

        self.assertEqual(output, bound)

    def test_synopsis_empty_evidence_gap_is_moved_to_uncertainty(self):
        output = {
            "findings": [
                {
                    "finding_id": "finding_missing_sample_size",
                    "status": "insufficient_evidence",
                    "title": "原文未提供样本量策略",
                    "source_id": "synopsis_chunk_1",
                    "evidence_span_ids": [],
                },
                {
                    "finding_id": "finding_phase",
                    "status": "supported",
                    "title": "研究分期为II期",
                    "source_id": "synopsis_chunk_1",
                    "evidence_span_ids": ["ev_phase"],
                },
            ],
            "uncertainties": [],
        }

        normalized = normalize_protocol_synopsis_missing_findings(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            output,
        )

        self.assertEqual(["finding_phase"], [item["finding_id"] for item in normalized["findings"]])
        self.assertEqual(
            [{"level": "data_gap", "description": "原文未提供样本量策略"}],
            normalized["uncertainties"],
        )

    def test_synopsis_source_free_non_default_value_is_reset_and_marked_missing(self):
        output = {
            "findings": [],
            "uncertainties": [],
            "study_definition": {
                "framing": {"development_regions": ["中国"], "study_phase": "II期"},
                "picos": {},
                "synopsis_text": "II期研究。",
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {
                    "framing.development_regions": [],
                    "framing.study_phase": [],
                },
            },
        }

        normalized = normalize_protocol_synopsis_missing_findings(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            output,
        )

        self.assertEqual({}, normalized["study_definition"]["field_evidence_span_ids"])
        self.assertEqual(["中国"], normalized["study_definition"]["framing"]["development_regions"])
        self.assertEqual("", normalized["study_definition"]["framing"]["study_phase"])
        self.assertNotIn(
            "framing.development_regions",
            normalized["study_definition"]["missing_fields"],
        )
        self.assertIn(
            "framing.study_phase",
            normalized["study_definition"]["missing_fields"],
        )
        errors = object.__new__(AiTaskRunner)._validate_protocol_synopsis_nested_contract(
            normalized["study_definition"]
        )
        self.assertEqual([], errors)

    def test_synopsis_instrument_item_evidence_derives_field_level_union(self):
        output = {
            "findings": [],
            "uncertainties": [],
            "study_definition": {
                "framing": {},
                "picos": {
                    "assessment_instruments": [
                        {
                            "instrument_id": "instrument_iga",
                            "canonical_name_zh": "研究者整体评分",
                            "evidence_span_ids": ["ev_iga", "ev_shared"],
                        },
                        {
                            "instrument_id": "instrument_dlqi",
                            "canonical_name_zh": "皮肤病生活质量指数",
                            "evidence_span_ids": ["ev_dlqi", "ev_shared"],
                        },
                    ]
                },
                "synopsis_text": "采用IGA和DLQI进行评价。",
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {},
            },
        }

        normalized = normalize_protocol_synopsis_missing_findings(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            output,
        )

        self.assertEqual(
            ["ev_iga", "ev_shared", "ev_dlqi"],
            normalized["study_definition"]["field_evidence_span_ids"][
                "picos.assessment_instruments"
            ],
        )
        self.assertEqual(
            2,
            len(normalized["study_definition"]["picos"]["assessment_instruments"]),
        )

    def test_synopsis_supported_finding_without_evidence_is_not_repaired(self):
        output = {
            "findings": [
                {
                    "finding_id": "finding_phase",
                    "status": "supported",
                    "title": "研究分期为II期",
                    "source_id": "synopsis_chunk_1",
                    "evidence_span_ids": [],
                }
            ],
            "uncertainties": [],
        }

        self.assertIs(
            output,
            normalize_protocol_synopsis_missing_findings(
                AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
                output,
            ),
        )

    def test_registered_source_text_is_bound_without_changing_translation_content(self) -> None:
        output = translation_output()
        output["evidence_spans"][0]["quote"] = "Participants must not receive SCS within 14 days"
        source = AiTaskSourceRef(
            source_id="wref_span_001",
            source_type="ctgov_protocol_span",
            title="NCT05014438 protocol span",
            locator="ctgov:NCT05014438:Prot_SAP_000.pdf:p12:b4",
            text_preview="Participants must not receive SCS within 14 days.",
            project_id="proj_rux_03_002",
            module="medical_writing",
        )

        bound = bind_exact_source_quotes(
            AiTaskType.REGULATORY_TRANSLATION_ZH,
            output,
            [source],
        )

        self.assertEqual(source.text_preview, bound["evidence_spans"][0]["quote"])
        self.assertEqual(output["translation"], bound["translation"])
        self.assertEqual("Participants must not receive SCS within 14 days", output["evidence_spans"][0]["quote"])

    def test_unknown_or_wrong_locator_is_not_silently_rebound(self) -> None:
        output = translation_output()
        output["evidence_spans"][0]["locator"] = "ctgov:wrong"
        source = AiTaskSourceRef(
            source_id="wref_span_001",
            source_type="ctgov_protocol_span",
            title="NCT05014438 protocol span",
            locator="ctgov:NCT05014438:Prot_SAP_000.pdf:p12:b4",
            text_preview="Participants must not receive SCS within 14 days.",
            project_id="proj_rux_03_002",
            module="medical_writing",
        )

        self.assertIs(
            output,
            bind_exact_source_quotes(AiTaskType.REGULATORY_TRANSLATION_ZH, output, [source]),
        )

    def test_translation_rejects_unrequested_regulatory_authority_claim(self) -> None:
        output = translation_output()
        output["translation"]["rationale"] = "该译法符合NMPA和ICH标准术语。"
        source = AiTaskSourceRef(
            source_id="wref_span_001",
            source_type="ctgov_protocol_span",
            title="NCT05014438 protocol span",
            locator="ctgov:NCT05014438:Prot_SAP_000.pdf:p12:b4",
            text_preview="Participants must not receive SCS within 14 days.",
            project_id="proj_rux_03_002",
            module="medical_writing",
        )

        errors = object.__new__(AiTaskRunner)._validate_run_output(
            "translation_001",
            AiTaskType.REGULATORY_TRANSLATION_ZH,
            output,
            allowed_sources=[source],
            forbidden_source_ids=[],
            expected_provider="openai_compatible",
            expected_model="configured-model",
            expected_prompt_version="regulatory_translation_zh_v0_5",
            expected_task_context={"glossary_version": "cms_regulatory_zh_v1"},
        )

        self.assertIn(
            "regulatory translation cites unrequested external authority: NMPA",
            errors,
        )
        self.assertIn(
            "regulatory translation cites unrequested external authority: ICH",
            errors,
        )

    def test_synopsis_runner_rejects_invalid_nested_framing_and_picos_types(self) -> None:
        source = AiTaskSourceRef(
            source_id="synopsis_chunk_1",
            source_type="project_protocol_synopsis",
            title="项目方案摘要原文片段 1",
            locator="synopsis:source_1:docx:paragraph:2",
            text_preview="本研究为类风湿关节炎II期随机双盲安慰剂对照研究。",
            project_id="proj_ra",
            module="medical_writing",
        )
        output = {
            "task_id": "synopsis_001",
            "task_type": "protocol_synopsis_structuring",
            "provider": "openai_compatible",
            "model": "configured-model",
            "prompt_version": "protocol_synopsis_structuring_v0_1",
            "input_source_ids": [source.source_id],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "synopsis_ev_1",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": source.text_preview,
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "study_definition": {
                "framing": {"intrinsic_objectives": "概念验证"},
                "picos": {"visit_strategy": ["第4周", "第8周"]},
                "synopsis_text": "本研究为II期随机双盲安慰剂对照研究。",
                "missing_fields": [],
                "conflict_notes": [],
                "field_evidence_span_ids": {},
            },
        }

        errors = object.__new__(AiTaskRunner)._validate_run_output(
            "synopsis_001",
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            output,
            allowed_sources=[source],
            forbidden_source_ids=[],
            expected_provider="openai_compatible",
            expected_model="configured-model",
            expected_prompt_version="protocol_synopsis_structuring_v0_1",
            expected_task_context={},
        )

        self.assertTrue(any("framing.intrinsic_objectives" in error for error in errors))
        self.assertTrue(any("picos.visit_strategy" in error for error in errors))
        self.assertFalse(any("概念验证" in error or "第4周" in error for error in errors))

    def test_prompt_pins_translation_contract_and_pending_medical_status(self) -> None:
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="translation_001",
                task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
                prompt_version="regulatory_translation_zh_v0_5",
                allowed_sources=[
                    AiSourceRef(
                        source_id="wref_span_001",
                        source_type="ctgov_protocol_span",
                        title="NCT05014438 protocol span",
                        locator="ctgov:NCT05014438:Prot_SAP_000.pdf:p12:b4",
                        text_preview="Participants must not receive SCS within 14 days.",
                    )
                ],
                task_context={
                    "glossary_version": "cms_regulatory_zh_v1",
                    "source_span_revision": "wref_span_001_r1",
                    "document_sha256": "a" * 64,
                },
            )
        )
        contract = envelope.payload["task_specific_output_contract"]["translation"]
        self.assertEqual(
            ["evidence_span_ids", "glossary_version", "rationale", "translated_text"],
            contract["required_keys"],
        )
        self.assertIn("pending medical-approval", contract["note"])
        self.assertIn("数字", envelope.system_prompt)
        self.assertIn("不得引用allowed_sources未出现的CDE", envelope.system_prompt)

    def test_translation_output_requires_closed_schema_evidence_and_medical_confirmation(self) -> None:
        self.assertEqual([], validate_ai_output(translation_output()))

        extra = translation_output()
        extra["translation"]["approved"] = True
        self.assertIn(
            "translation contains unexpected key: approved",
            validate_ai_output(extra),
        )
        overclaim = translation_output()
        overclaim["translation"]["translated_text"] = "该内容已医学批准。"
        self.assertTrue(
            any("forbidden translation claim" in item for item in validate_ai_output(overclaim))
        )

    def test_trusted_internal_policy_accepts_only_pinned_translation_context(self) -> None:
        resolver = AiExecutionPolicyResolver(
            deployment_profile="approved_private_documents",
            provider_name="openai_compatible",
            model_name="configured-model",
            test_only_provider_injection=True,
        )
        source = AiTaskSourceRef(
            source_id="wref_span_001",
            source_type="ctgov_protocol_span",
            title="NCT05014438 protocol span",
            locator="ctgov:NCT05014438:doc:p12:b4",
            text_preview="Participants must not receive SCS within 14 days.",
            project_id="proj_rux_03_002",
            module="medical_writing",
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="regulatory_translation_zh",
            prompt_version="regulatory_translation_zh_v0_5",
            allowed_sources=[source],
            task_context={
                "glossary_version": "cms_regulatory_zh_v1",
                "source_span_revision": "wref_span_001_r1",
                "document_sha256": "a" * 64,
            },
        )
        resolution = resolver.resolve_internal("proj_rux_03_002", request)
        self.assertEqual("cms_regulatory_zh_v1", resolution.task_context["glossary_version"])

        invalid = request.model_copy(update={"task_context": {"glossary_version": "v1"}})
        with self.assertRaises(AiExecutionPolicyDenied):
            resolver.resolve_internal("proj_rux_03_002", invalid)


if __name__ == "__main__":
    unittest.main()
