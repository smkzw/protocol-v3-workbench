"""Unit tests for conversational fact intake (IB-optional).

These tests exercise the contract layer, the schema-bound prompt builder,
the field-path allowlist enforcement, the persistent conversation state
with optimistic revision checks, and the idempotent turn/apply operations.
They use an in-memory fake provider so no DeepSeek V4 Pro credentials are
required and no network is used.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from packages.contracts.workbench_contracts import (
    MedicalWritingFactIntakeApplyDecision,
    MedicalWritingFactIntakeApplyRequest,
    MedicalWritingFactIntakeConflictError,
    MedicalWritingFactIntakeConversationCreateRequest,
    MedicalWritingFactIntakeFactKind,
    MedicalWritingFactIntakeProposal,
    MedicalWritingFactIntakeProposalDecision,
    MedicalWritingFactIntakeScope,
    MedicalWritingFactIntakeTurnKind,
    MedicalWritingFactIntakeTurnRequest,
)
from services.api.app.ai_gateway import (
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiProviderRuntimeError,
    DisabledAiProvider,
)
from services.api.app.medical_writing_fact_intake import (
    FACT_INTAKE_PROMPT_VERSION,
    HIGH_IMPACT_BLOCKED_CLAUSES,
    MedicalWritingFactIntakeService,
    _recompute_blocked_clauses,
    _recompute_status,
    _validate_ai_response,
)


class FakeFactIntakeProvider:
    """Records envelopes and returns scripted responses."""

    provider_name = "fake_deepseek"
    model_name = "deepseek-v4-pro"

    def __init__(self, responses: List[Dict[str, Any]]):
        self._responses = list(responses)
        self.envelopes: List[AiPromptEnvelope] = []

    def run(self, envelope: AiPromptEnvelope) -> Dict[str, Any]:
        self.envelopes.append(envelope)
        if not self._responses:
            raise AssertionError("FakeFactIntakeProvider ran out of scripted responses")
        return self._responses.pop(0)


def _ra_response(
    *,
    response_text: str = "已记录类风湿关节炎 II 期信息。",
    proposals: List[Dict[str, Any]] | None = None,
    questions: List[str] | None = None,
    high_impact_missing: List[str] | None = None,
) -> Dict[str, Any]:
    return {
        "response_text": response_text,
        "proposals": proposals or [],
        "questions": questions or [],
        "high_impact_missing": high_impact_missing or [],
        "uncertainties": [],
        "needs_medical_confirmation": True,
    }


class FactIntakeContractTests(unittest.TestCase):
    def test_unknown_fact_kind_must_not_carry_value(self):
        with self.assertRaises(Exception):
            MedicalWritingFactIntakeProposal(
                proposal_id="p1",
                field_path="framing.indication",
                fact_kind=MedicalWritingFactIntakeFactKind.UNKNOWN,
                value="RA",
            )

    def test_user_stated_fact_requires_value(self):
        with self.assertRaises(Exception):
            MedicalWritingFactIntakeProposal(
                proposal_id="p1",
                field_path="framing.indication",
                fact_kind=MedicalWritingFactIntakeFactKind.USER_STATED,
                value="",
            )

    def test_pending_proposal_must_not_carry_decision_fields(self):
        now_iso_str = "2026-07-18T00:00:00+00:00"
        from datetime import datetime, timezone

        decided = datetime(2026, 7, 18, tzinfo=timezone.utc)
        with self.assertRaises(Exception):
            MedicalWritingFactIntakeProposal(
                proposal_id="p1",
                field_path="framing.indication",
                fact_kind=MedicalWritingFactIntakeFactKind.USER_STATED,
                value="RA",
                decided_by="mm",
                decided_at=decided,
            )


class FactIntakeValidationTests(unittest.TestCase):
    def test_forbidden_field_path_is_rejected(self):
        bad = _ra_response(
            proposals=[
                {
                    "proposal_id": "p1",
                    "field_path": "framing.secret_field",
                    "fact_kind": "user_stated",
                    "value": "x",
                    "rationale": "x",
                }
            ]
        )
        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)

    def test_fabricated_high_impact_value_is_rejected(self):
        bad = _ra_response(
            proposals=[
                {
                    "proposal_id": "p1",
                    "field_path": "high_impact_missing.first_in_human_starting_dose",
                    "fact_kind": "ai_inferred",
                    "value": "3 mg/kg",
                    "rationale": "from public label",
                    "confidence": "medium",
                }
            ]
        )
        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)

    def test_high_impact_missing_only_as_unknown(self):
        good = _ra_response(
            proposals=[
                {
                    "proposal_id": "p1",
                    "field_path": "high_impact_missing.first_in_human_starting_dose",
                    "fact_kind": "unknown",
                    "value": "",
                    "rationale": "用户未给出，IB 未提供",
                    "confidence": "unknown",
                }
            ],
            high_impact_missing=["high_impact_missing.first_in_human_starting_dose"],
        )
        proposals, questions, text, him = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING, good
        )
        self.assertEqual(1, len(proposals))
        self.assertEqual(MedicalWritingFactIntakeFactKind.UNKNOWN, proposals[0].fact_kind)
        self.assertEqual(
            ["high_impact_missing.first_in_human_starting_dose"], him
        )

    def test_explicit_user_high_impact_value_is_allowed_without_ai_inference(self):
        good = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_starting_dose",
                    "field_path": (
                        "framing.product_profile.confirmed_facts."
                        "first_in_human_starting_dose"
                    ),
                    "fact_kind": "user_stated",
                    "value": "3 mg/kg，静脉输注",
                    "rationale": "用户本轮明确提供起始剂量和给药途径",
                    "confidence": "high",
                }
            ],
        )

        proposals, _, _, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING, good
        )

        self.assertEqual("3 mg/kg，静脉输注", proposals[0].value)

    def test_ai_inferred_high_impact_value_is_rejected(self):
        bad = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_starting_dose",
                    "field_path": (
                        "framing.product_profile.confirmed_facts."
                        "first_in_human_starting_dose"
                    ),
                    "fact_kind": "ai_inferred",
                    "value": "3 mg/kg",
                    "rationale": "参考同靶点药物推断",
                    "confidence": "medium",
                }
            ],
        )

        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)

    def test_source_extracted_high_impact_value_requires_source_id(self):
        bad = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_starting_dose",
                    "field_path": (
                        "framing.product_profile.confirmed_facts."
                        "first_in_human_starting_dose"
                    ),
                    "fact_kind": "source_extracted",
                    "value": "3 mg/kg",
                    "rationale": "研究者手册给出",
                    "source_ids": [],
                    "confidence": "high",
                }
            ],
        )

        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)

    def test_source_extracted_fact_cannot_cite_unprovided_source(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_route",
                    "field_path": "framing.product_profile.administration_routes",
                    "fact_kind": "source_extracted",
                    "value": "静脉输注",
                    "rationale": "声称来自研究者手册",
                    "source_ids": ["fabricated_source"],
                    "confidence": "high",
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "not provided in source_evidence"):
            _validate_ai_response(
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                response,
                allowed_source_ids={"src_ib_span_1"},
            )

    def test_ib_history_cannot_overwrite_current_protocol_or_design(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_ib_version",
                    "field_path": "framing.version",
                    "fact_kind": "source_extracted",
                    "value": "4.0",
                    "rationale": "研究者手册版本为4.0",
                    "source_ids": ["src_ib_span_1"],
                    "confidence": "high",
                },
                {
                    "proposal_id": "p_prior_design",
                    "field_path": "framing.design_pattern",
                    "fact_kind": "source_extracted",
                    "value": "随机双盲安慰剂对照",
                    "rationale": "既往II期研究采用该设计",
                    "source_ids": ["src_ib_span_2"],
                    "confidence": "high",
                },
                {
                    "proposal_id": "p_modality",
                    "field_path": "framing.product_profile.technology_type",
                    "fact_kind": "source_extracted",
                    "value": "small_molecule",
                    "rationale": "研究者手册明确为小分子",
                    "source_ids": ["src_ib_span_3"],
                    "confidence": "high",
                },
            ]
        )

        proposals, _, response_text, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
            allowed_source_ids={
                "src_ib_span_1",
                "src_ib_span_2",
                "src_ib_span_3",
            },
            source_evidence_by_id={
                "src_ib_span_1": "研究者手册版本4.0",
                "src_ib_span_2": "既往II期研究采用随机双盲安慰剂对照设计",
                "src_ib_span_3": "本品为小分子药物",
            },
        )

        self.assertEqual(
            ["framing.product_profile.technology_type"],
            [item.field_path for item in proposals],
        )
        self.assertIn("系统已隔离2项", response_text)

    def test_tested_doses_are_not_accepted_as_rp2d(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_rp2d",
                    "field_path": (
                        "framing.product_profile.confirmed_facts."
                        "recommended_phase2_dose"
                    ),
                    "fact_kind": "source_extracted",
                    "value": "40 mg和80 mg",
                    "rationale": "II期研究测试了40 mg和80 mg剂量",
                    "source_ids": ["src_ib_span_1"],
                    "confidence": "high",
                }
            ]
        )

        proposals, _, response_text, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
            allowed_source_ids={"src_ib_span_1"},
            source_evidence_by_id={
                "src_ib_span_1": "II期研究设置40 mg和80 mg两个剂量组"
            },
        )

        self.assertEqual([], proposals)
        self.assertIn("recommended_phase2_dose", response_text)

    def test_prior_study_evidence_has_a_non_current_destination(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_prior_regimen",
                    "field_path": (
                        "framing.product_profile.historical_dose_regimens"
                    ),
                    "fact_kind": "source_extracted",
                    "value": "既往MAD研究：10-80 mg，每日一次，连续7天",
                    "rationale": "研究者手册明确描述既往MAD队列",
                    "source_ids": ["src_ib_span_1"],
                    "confidence": "high",
                },
                {
                    "proposal_id": "p_prior_design",
                    "field_path": (
                        "framing.product_profile.historical_population_designs"
                    ),
                    "fact_kind": "source_extracted",
                    "value": "既往II期：RA患者，随机、双盲、安慰剂和阳性药对照",
                    "rationale": "研究者手册明确描述既往II期人群和设计",
                    "source_ids": ["src_ib_span_2"],
                    "confidence": "high",
                },
            ]
        )

        proposals, _, _, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
            allowed_source_ids={"src_ib_span_1", "src_ib_span_2"},
            source_evidence_by_id={
                "src_ib_span_1": "MAD研究10-80 mg，每日一次，连续给药7天。",
                "src_ib_span_2": "既往II期RA研究采用随机双盲安慰剂及阳性药对照。",
            },
        )

        self.assertEqual(
            [
                "framing.product_profile.historical_dose_regimens",
                "framing.product_profile.historical_population_designs",
            ],
            [proposal.field_path for proposal in proposals],
        )

    def test_ai_inference_cannot_be_stored_as_historical_source_evidence(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_inferred_history",
                    "field_path": (
                        "framing.product_profile.historical_study_summaries"
                    ),
                    "fact_kind": "ai_inferred",
                    "value": "可能已完成首次患者研究",
                    "rationale": "根据开发阶段推测",
                    "source_ids": [],
                    "confidence": "low",
                }
            ]
        )

        proposals, _, response_text, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
        )

        self.assertEqual([], proposals)
        self.assertIn("historical_study_summaries", response_text)

    def test_explicit_rp2d_source_statement_is_retained_for_user_confirmation(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_rp2d",
                    "field_path": (
                        "framing.product_profile.confirmed_facts."
                        "recommended_phase2_dose"
                    ),
                    "fact_kind": "source_extracted",
                    "value": "40 mg QD",
                    "rationale": "原文明确表述推荐II期剂量为40 mg QD",
                    "source_ids": ["src_ib_span_1"],
                    "confidence": "high",
                }
            ]
        )

        proposals, _, _, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
            allowed_source_ids={"src_ib_span_1"},
            source_evidence_by_id={
                "src_ib_span_1": "基于暴露-反应分析，推荐II期剂量为40 mg QD。"
            },
        )

        self.assertEqual("40 mg QD", proposals[0].value)

    def test_low_value_current_study_questions_are_filtered_from_ib_fact_intake(self):
        response = _ra_response(
            questions=[
                "本方案采用何种研究设计？",
                "开发区域是否仅限于中国？",
                "是否已有明确的非临床安全边际？",
            ]
        )

        _, questions, _, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            response,
            restrict_questions_to_product_facts=True,
        )

        self.assertEqual(["是否已有明确的非临床安全边际？"], questions)

    def test_enum_aliases_are_normalized_to_persistable_contract_values(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_phase",
                    "field_path": "framing.study_phase",
                    "fact_kind": "user_stated",
                    "value": "I",
                    "rationale": "用户说明为I期",
                    "confidence": "high",
                },
                {
                    "proposal_id": "p_modality",
                    "field_path": "framing.product_profile.technology_type",
                    "fact_kind": "user_stated",
                    "value": "单克隆抗体",
                    "rationale": "用户说明为单克隆抗体",
                    "confidence": "high",
                },
            ],
        )

        proposals, _, _, _ = _validate_ai_response(
            MedicalWritingFactIntakeScope.STUDY_FRAMING, response
        )

        self.assertEqual("I期", proposals[0].value)
        self.assertEqual("monoclonal_antibody", proposals[1].value)

    def test_invalid_enum_value_is_rejected_before_framing_write(self):
        response = _ra_response(
            proposals=[
                {
                    "proposal_id": "p_modality",
                    "field_path": "framing.product_profile.technology_type",
                    "fact_kind": "ai_inferred",
                    "value": "随便写的剂型",
                    "rationale": "无",
                    "confidence": "low",
                }
            ],
        )

        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, response)

    def test_more_than_three_questions_rejected(self):
        bad = _ra_response(questions=["q1", "q2", "q3", "q4"])
        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)

    def test_unknown_response_text_rejected(self):
        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, {})

    def test_high_impact_missing_must_be_allowed_path(self):
        bad = _ra_response(
            high_impact_missing=["high_impact_missing.invented_field"],
        )
        with self.assertRaises(ValueError):
            _validate_ai_response(MedicalWritingFactIntakeScope.STUDY_FRAMING, bad)


class FactIntakeStatusTests(unittest.TestCase):
    def test_no_high_impact_missing_is_sufficient_for_writing(self):
        status = _recompute_status(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            confirmed={
                "framing.indication": "RA",
                "framing.study_phase": "II",
                "framing.investigational_product": "CMP-001",
            },
            unresolved_high_impact=[],
        )
        self.assertEqual("sufficient_for_writing_candidates", status)

    def test_missing_high_impact_blocks_only_writing_not_research(self):
        status = _recompute_status(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            confirmed={
                "framing.indication": "RA",
                "framing.study_phase": "II",
                "framing.investigational_product": "CMP-001",
            },
            unresolved_high_impact=["high_impact_missing.safety_threshold"],
        )
        self.assertEqual("sufficient_for_research", status)
        # research and corpus prep remain unblocked: blocked clauses are the
        # deterministic writing clauses only.
        blocked = _recompute_blocked_clauses(["high_impact_missing.safety_threshold"])
        self.assertIn("safety_assessments.safety_threshold_rules", blocked)
        self.assertIn("dose_modification_rules.threshold_rules", blocked)

    def test_missing_required_framing_keeps_collecting(self):
        status = _recompute_status(
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            confirmed={
                "framing.indication": "RA",
                "framing.study_phase": "II",
            },
            unresolved_high_impact=[],
        )
        self.assertEqual("collecting", status)


class FactIntakeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "fact_intake.sqlite3"
        self.provider = FakeFactIntakeProvider([])
        self.service = MedicalWritingFactIntakeService(
            self.db_path, provider_factory=lambda: self.provider
        )
        self.project_id = "proj_ra_fact_intake"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create(self, idempotency_key: str = "create-1"):
        return self.service.create(
            self.project_id,
            MedicalWritingFactIntakeConversationCreateRequest(
                scope=MedicalWritingFactIntakeScope.STUDY_FRAMING,
                actor="medical_manager",
                idempotency_key=idempotency_key,
            ),
        )

    def _ra_first_turn(self):
        self.provider._responses.append(
            _ra_response(
                proposals=[
                    {
                        "proposal_id": "p_indication",
                        "field_path": "framing.indication",
                        "fact_kind": "user_stated",
                        "value": "类风湿关节炎",
                        "rationale": "用户明确说类风湿关节炎",
                        "confidence": "high",
                    },
                    {
                        "proposal_id": "p_phase",
                        "field_path": "framing.study_phase",
                        "fact_kind": "user_stated",
                        "value": "II期",
                        "rationale": "用户说 II 期",
                        "confidence": "high",
                    },
                    {
                        "proposal_id": "p_product",
                        "field_path": "framing.investigational_product",
                        "fact_kind": "user_stated",
                        "value": "CMP-001",
                        "rationale": "用户给出代号",
                        "confidence": "high",
                    },
                    {
                        "proposal_id": "p_dose",
                        "field_path": "high_impact_missing.first_in_human_starting_dose",
                        "fact_kind": "unknown",
                        "value": "",
                        "rationale": "用户未给出起始剂量，IB 未提供",
                        "confidence": "unknown",
                    },
                ],
                questions=["是否已有 IB？", "目标人群是否包含 bDMARDs 经治患者？"],
                high_impact_missing=[
                    "high_impact_missing.first_in_human_starting_dose"
                ],
            )
        )

    def test_conversation_create_is_idempotent(self):
        conv = self._create("create-1")
        self.assertEqual(1, conv.revision)
        self.assertEqual("collecting", conv.status)
        # replay with same idempotency key returns the same conversation
        replay = self._create("create-1")
        self.assertEqual(conv.conversation_id, replay.conversation_id)
        # a different key conflicts
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self._create("create-2")

    def test_create_seeds_existing_project_facts_without_claiming_writing_ready(self):
        conversation = self.service.create(
            self.project_id,
            MedicalWritingFactIntakeConversationCreateRequest(
                scope=MedicalWritingFactIntakeScope.STUDY_FRAMING,
                actor="medical_manager",
                idempotency_key="create-seeded",
            ),
            initial_confirmed_field_values={
                "framing.indication": "类风湿关节炎",
                "framing.study_phase": "I",
                "framing.investigational_product": "CMP-001",
                "framing.secret_field": "must be ignored",
            },
        )

        self.assertEqual(
            {
                "framing.indication": "类风湿关节炎",
                "framing.study_phase": "I期",
                "framing.investigational_product": "CMP-001",
            },
            conversation.confirmed_field_values,
        )
        self.assertEqual("sufficient_for_research", conversation.status)
        self.assertEqual([], conversation.messages)
        self.assertEqual([], conversation.open_proposals)

    def test_turn_without_ib_records_facts_and_keeps_research_open(self):
        self._create("create-1")
        self._ra_first_turn()
        result = self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="我们做的是类风湿关节炎的II期，药物是个单抗叫CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        self.assertEqual(2, result.conversation.revision)
        self.assertEqual(4, len(result.proposals))
        self.assertEqual(2, len(result.questions))
        # user + ai messages preserved verbatim
        self.assertEqual(2, len(result.conversation.messages))
        self.assertEqual(
            MedicalWritingFactIntakeTurnKind.USER_MESSAGE,
            result.conversation.messages[0].turn_kind,
        )
        self.assertEqual(
            MedicalWritingFactIntakeTurnKind.AI_RESPONSE,
            result.conversation.messages[1].turn_kind,
        )
        # high-impact missing recorded, blocked clauses local
        self.assertIn(
            "high_impact_missing.first_in_human_starting_dose",
            result.conversation.unresolved_high_impact_fields,
        )
        self.assertIn(
            "intervention_sections.starting_dose",
            result.conversation.locally_blocked_clauses,
        )

    def test_turn_idempotency_replays_same_result(self):
        self._create("create-1")
        self._ra_first_turn()
        first = self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="类风湿关节炎 II 期 CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        # second call with the same key and content returns the same result
        # without consuming another scripted provider response.
        second = self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="类风湿关节炎 II 期 CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        self.assertEqual(
            first.conversation.revision, second.conversation.revision
        )
        self.assertEqual(
            first.ai_message.message_id, second.ai_message.message_id
        )

    def test_new_pending_candidate_supersedes_older_candidate_for_same_field(self):
        self._create("create-1")
        self.provider._responses.extend(
            [
                _ra_response(
                    proposals=[
                        {
                            "proposal_id": "p_target_old",
                            "field_path": "framing.target_mechanism",
                            "fact_kind": "ai_inferred",
                            "value": "旧候选机制",
                            "rationale": "第一轮推断",
                            "confidence": "low",
                        }
                    ]
                ),
                _ra_response(
                    proposals=[
                        {
                            "proposal_id": "p_target_new",
                            "field_path": "framing.target_mechanism",
                            "fact_kind": "user_stated",
                            "value": "IRAK4抑制剂",
                            "rationale": "用户第二轮明确说明",
                            "confidence": "high",
                        }
                    ]
                ),
            ]
        )
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="先生成候选",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-old",
            ),
        )
        result = self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=2,
                message_text="靶点机制明确为IRAK4抑制剂",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-new",
            ),
        )

        self.assertEqual(
            ["p_target_new"],
            [
                proposal.proposal_id
                for proposal in result.conversation.open_proposals
                if proposal.field_path == "framing.target_mechanism"
            ],
        )

    def test_turn_idempotency_key_reuse_with_different_content_conflicts(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="first text",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self.service.turn(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeTurnRequest(
                    expected_revision=1,
                    message_text="different text",
                    ib_status="not_provided",
                    actor="medical_manager",
                    idempotency_key="turn-1",
                ),
            )

    def test_stale_expected_revision_is_rejected(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self.service.turn(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeTurnRequest(
                    expected_revision=1,  # stale: current is 2
                    message_text="another message",
                    ib_status="not_provided",
                    actor="medical_manager",
                    idempotency_key="turn-2",
                ),
            )

    def test_apply_adopt_confirms_fact_and_unblocks_when_no_high_impact(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        result = self.service.apply(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeApplyRequest(
                expected_revision=2,
                decisions=[
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_indication", action="adopt"
                    ),
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_phase", action="adopt"
                    ),
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_product", action="adopt"
                    ),
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_dose", action="reject",
                        note="待 IB 提供",
                    ),
                ],
                actor="medical_manager",
                idempotency_key="apply-1",
            ),
        )
        self.assertEqual(3, result.conversation.revision)
        self.assertEqual("类风湿关节炎", result.conversation.confirmed_field_values["framing.indication"])
        self.assertEqual("II期", result.conversation.confirmed_field_values["framing.study_phase"])
        self.assertEqual("CMP-001", result.conversation.confirmed_field_values["framing.investigational_product"])
        # high-impact dose remains unresolved -> research open, writing blocked
        self.assertEqual("sufficient_for_research", result.conversation.status)
        self.assertIn(
            "high_impact_missing.first_in_human_starting_dose",
            result.conversation.unresolved_high_impact_fields,
        )

    def test_apply_edit_records_edited_value_as_confirmed(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        result = self.service.apply(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeApplyRequest(
                expected_revision=2,
                decisions=[
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_indication",
                        action="edit",
                        edited_value="类风湿关节炎（成人）",
                    ),
                ],
                actor="medical_manager",
                idempotency_key="apply-edit-1",
            ),
        )
        self.assertEqual(
            "类风湿关节炎（成人）",
            result.conversation.confirmed_field_values["framing.indication"],
        )
        # the decided proposal carries the edited marker
        decided = next(
            p for p in result.conversation.open_proposals
            if p.proposal_id == "p_indication"
        )
        self.assertEqual(
            MedicalWritingFactIntakeProposalDecision.EDITED, decided.decision
        )
        self.assertEqual("类风湿关节炎（成人）", decided.edited_value)

    def test_adopted_explicit_high_impact_value_resolves_only_paired_gap(self):
        self._create("create-1")
        self.provider._responses.append(
            _ra_response(
                proposals=[
                    {
                        "proposal_id": "p_starting_dose",
                        "field_path": (
                            "framing.product_profile.confirmed_facts."
                            "first_in_human_starting_dose"
                        ),
                        "fact_kind": "user_stated",
                        "value": "3 mg/kg，静脉输注",
                        "rationale": "用户明确给出",
                        "confidence": "high",
                    }
                ],
                high_impact_missing=[
                    "high_impact_missing.first_in_human_starting_dose",
                    "high_impact_missing.safety_threshold",
                ],
            )
        )
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="FIH起始剂量明确为3 mg/kg，静脉输注",
                ib_status="not_available",
                actor="medical_manager",
                idempotency_key="turn-explicit-dose",
            ),
        )

        result = self.service.apply(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeApplyRequest(
                expected_revision=2,
                decisions=[
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_starting_dose",
                        action="adopt",
                    )
                ],
                actor="medical_manager",
                idempotency_key="apply-explicit-dose",
            ),
        )

        confirmed_path = (
            "framing.product_profile.confirmed_facts."
            "first_in_human_starting_dose"
        )
        self.assertEqual(
            "3 mg/kg，静脉输注",
            result.confirmed_field_values[confirmed_path],
        )
        self.assertNotIn(
            "high_impact_missing.first_in_human_starting_dose",
            result.conversation.unresolved_high_impact_fields,
        )
        self.assertIn(
            "high_impact_missing.safety_threshold",
            result.conversation.unresolved_high_impact_fields,
        )

    def test_apply_idempotency_and_stale_revision(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        req = MedicalWritingFactIntakeApplyRequest(
            expected_revision=2,
            decisions=[
                MedicalWritingFactIntakeApplyDecision(
                    proposal_id="p_indication", action="adopt"
                ),
            ],
            actor="medical_manager",
            idempotency_key="apply-1",
        )
        first = self.service.apply(
            self.project_id, MedicalWritingFactIntakeScope.STUDY_FRAMING, req
        )
        # idempotent replay
        replay = self.service.apply(
            self.project_id, MedicalWritingFactIntakeScope.STUDY_FRAMING, req
        )
        self.assertEqual(
            first.conversation.revision, replay.conversation.revision
        )
        # A different request cannot reverse or repeat a medical manager's
        # completed decision for the same proposal.
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self.service.apply(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeApplyRequest(
                    expected_revision=first.conversation.revision,
                    decisions=[
                        MedicalWritingFactIntakeApplyDecision(
                            proposal_id="p_indication", action="reject"
                        ),
                    ],
                    actor="medical_manager",
                    idempotency_key="apply-redecide",
                ),
            )
        # stale revision rejected
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self.service.apply(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeApplyRequest(
                    expected_revision=2,  # stale
                    decisions=[
                        MedicalWritingFactIntakeApplyDecision(
                            proposal_id="p_phase", action="adopt"
                        ),
                    ],
                    actor="medical_manager",
                    idempotency_key="apply-2",
                ),
            )

    def test_apply_reject_does_not_confirm_fact(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        result = self.service.apply(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeApplyRequest(
                expected_revision=2,
                decisions=[
                    MedicalWritingFactIntakeApplyDecision(
                        proposal_id="p_indication", action="reject", note="措辞不准确"
                    ),
                ],
                actor="medical_manager",
                idempotency_key="apply-reject-1",
            ),
        )
        self.assertNotIn(
            "framing.indication", result.conversation.confirmed_field_values
        )
        decided = next(
            p for p in result.conversation.open_proposals
            if p.proposal_id == "p_indication"
        )
        self.assertEqual(
            MedicalWritingFactIntakeProposalDecision.REJECTED, decided.decision
        )

    def test_disabled_provider_raises_configuration_conflict(self):
        service = MedicalWritingFactIntakeService(
            self.db_path, provider_factory=lambda: DisabledAiProvider()
        )
        service.create(
            self.project_id,
            MedicalWritingFactIntakeConversationCreateRequest(
                scope=MedicalWritingFactIntakeScope.STUDY_FRAMING,
                actor="medical_manager",
                idempotency_key="create-1",
            ),
        )
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            service.turn(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeTurnRequest(
                    expected_revision=1,
                    message_text="RA II",
                    ib_status="not_provided",
                    actor="medical_manager",
                    idempotency_key="turn-1",
                ),
            )

    def test_uploaded_ib_without_source_ids_rejected_by_contract(self):
        with self.assertRaises(Exception):
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II",
                ib_status="uploaded",
                ib_source_ids=[],
                actor="medical_manager",
                idempotency_key="turn-1",
            )

    def test_apply_unknown_proposal_id_conflicts(self):
        self._create("create-1")
        self._ra_first_turn()
        self.service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="RA II CMP-001",
                ib_status="not_provided",
                actor="medical_manager",
                idempotency_key="turn-1",
            ),
        )
        with self.assertRaises(MedicalWritingFactIntakeConflictError):
            self.service.apply(
                self.project_id,
                MedicalWritingFactIntakeScope.STUDY_FRAMING,
                MedicalWritingFactIntakeApplyRequest(
                    expected_revision=2,
                    decisions=[
                        MedicalWritingFactIntakeApplyDecision(
                            proposal_id="does_not_exist", action="adopt"
                        ),
                    ],
                    actor="medical_manager",
                    idempotency_key="apply-1",
                ),
            )

    def test_envelope_carries_allowlist_and_forbids_inventing_high_impact(self):
        # Sanity: the system prompt explicitly lists the high-impact fields
        # as unknown-only and lists the allowlist verbatim.
        from services.api.app.medical_writing_fact_intake import (
            build_fact_intake_envelope,
            STUDY_FRAMING_ALLOWED_FIELD_PATHS,
        )

        env = build_fact_intake_envelope(
            scope=MedicalWritingFactIntakeScope.STUDY_FRAMING,
            message_text="RA II",
            ib_status="not_provided",
            ib_source_ids=[],
            confirmed_field_values={},
            open_high_impact_missing=[],
        )
        self.assertIn("framing.indication", env.system_prompt)
        self.assertIn(
            "high_impact_missing.first_in_human_starting_dose", env.system_prompt
        )
        allowed_in_payload = env.payload["schema"]["allowed_field_paths"]
        self.assertIn("framing.indication", allowed_in_payload)
        self.assertIn(
            "high_impact_missing.first_in_human_starting_dose",
            allowed_in_payload,
        )
        # high-impact fields are in the allowlist as missing-only paths
        self.assertIn(
            "high_impact_missing.first_in_human_starting_dose",
            STUDY_FRAMING_ALLOWED_FIELD_PATHS,
        )
        self.assertIn(
            (
                "framing.product_profile.confirmed_facts."
                "first_in_human_starting_dose"
            ),
            STUDY_FRAMING_ALLOWED_FIELD_PATHS,
        )
        self.assertIn("严禁使用 ai_inferred", env.system_prompt)
        self.assertIn("不得追问方案号、方案标题", env.system_prompt)
        self.assertEqual(
            [
                "unknown",
                "monoclonal_antibody",
                "other_biologic",
                "small_molecule",
                "rna_therapy",
                "cell_therapy",
                "gene_therapy",
                "vaccine",
                "other",
            ],
            env.payload["schema"]["field_value_contracts"][
                "framing.product_profile.technology_type"
            ],
        )

    def test_uploaded_ib_original_spans_are_supplied_to_independent_ai(self):
        provider = FakeFactIntakeProvider(
            [
                _ra_response(
                    proposals=[
                        {
                            "proposal_id": "p_route",
                            "field_path": "framing.product_profile.administration_routes",
                            "fact_kind": "source_extracted",
                            "value": "静脉输注",
                            "rationale": "研究者手册原文明确给出静脉输注",
                            "source_ids": ["src_ib_span_1"],
                            "confidence": "high",
                        }
                    ]
                )
            ]
        )
        service = MedicalWritingFactIntakeService(
            self.db_path,
            provider_factory=lambda: provider,
            source_context_resolver=lambda project_id, source_ids, query_text: [
                {
                    "source_id": "src_ib_span_1",
                    "locator": "docx:paragraph:12",
                    "title": "CMS-RA-001研究者手册",
                    "text": "CMS-RA-001采用静脉输注给药。",
                }
            ],
        )
        service.create(
            self.project_id,
            MedicalWritingFactIntakeConversationCreateRequest(
                scope=MedicalWritingFactIntakeScope.STUDY_FRAMING,
                actor="medical_manager",
                idempotency_key="create-with-ib",
            ),
        )
        service.turn(
            self.project_id,
            MedicalWritingFactIntakeScope.STUDY_FRAMING,
            MedicalWritingFactIntakeTurnRequest(
                expected_revision=1,
                message_text="请提取研究者手册中的给药途径。",
                ib_status="parsed",
                ib_source_ids=["src_ib"],
                actor="medical_manager",
                idempotency_key="turn-with-ib",
            ),
        )

        evidence = provider.envelopes[0].payload["source_evidence"]
        self.assertEqual("src_ib_span_1", evidence[0]["source_id"])
        self.assertEqual("docx:paragraph:12", evidence[0]["locator"])
        self.assertIn("静脉输注", evidence[0]["text"])


if __name__ == "__main__":
    unittest.main()
