"""Failure-first contract tests for the additive structured intervention rules
contract (frozen schema ``medical_writing_intervention_rules_v1``).

These tests assert the contract mandated by the implementation context:

- Default authority is ``legacy``; legacy payloads round-trip unchanged.
- ``no_planned_adjustment`` requires a nonblank statement.
- ``protocol_defined`` requires at least one IP action rule.
- All IDs are present and unique across collections.
- Cross-object links must reference an existing non-IP source rule; a nonblank
  target rule id must reference an existing IP action rule.
- When structured authority is active, regimen / background / CM rules are
  projected into the four legacy compatibility fields, and IP action rules are
  NOT projected into the CM family.
- The D001-like separation is preserved: CM dose rules stay attached to the
  non-IP source rule; rescue -> IP hold/stop links survive without leaking
  CM dose rules into the IP-family projection.
- Impact routing on ``picos.intervention_rules`` includes
  ``dose_modification_rules``, ``non_investigational_interventions`` and
  ``concomitant_therapy_rules`` while legacy routes remain intact.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    InterventionRulesIpActionKind,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesLinkAction,
    InterventionRulesLinkSourceKind,
    InterventionRulesNonIpPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingInterventionCrossObjectLink,
    MedicalWritingInterventionIpActionRule,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)


def _complete_framing() -> MedicalWritingStudyFraming:
    return MedicalWritingStudyFraming(
        protocol_id="CMS-RA-201",
        version="V0.1",
        document_title="CMS-RA-201治疗类风湿关节炎的II期临床研究方案",
        indication="类风湿关节炎",
        clinicaltrials_condition_term="Rheumatoid Arthritis",
        study_phase="II期",
        intrinsic_objectives=["概念验证（PoC）", "剂量探索"],
        investigational_product="CMS-RA-201注射液",
        target_mechanism="靶向炎症通路的单克隆抗体",
        competitor_target_scope="同靶点及同机制生物制剂",
        development_regions=["中国"],
        design_pattern="随机、双盲、安慰剂对照、平行组、多中心研究",
        population_intent="既往csDMARD治疗反应不充分的中重度活动性类风湿关节炎成人患者",
        key_uncertainties=["剂量-效应关系", "第12周主要终点评价时点"],
    )


def _legacy_picos(**overrides) -> MedicalWritingPicosDefinition:
    payload = dict(
        design_archetype="randomized_confirmatory",
        population_summary="18至75岁中重度活动性类风湿关节炎试验参与者。",
        inclusion_modules=["筛选期与基线期满足疾病活动度阈值", "稳定使用背景甲氨蝶呤"],
        exclusion_modules=["活动性感染", "近期使用其他生物制剂且未完成洗脱"],
        washout_rules=["既往生物制剂按药代特征和方案规定完成洗脱"],
        intervention_summary="CMS-RA-201两个剂量组，皮下注射。",
        intervention_dose_regimen="每4周给药一次，持续24周。",
        allowed_concomitant_rules=["稳定剂量叶酸"],
        required_background_rules=["稳定剂量甲氨蝶呤"],
        prohibited_concomitant_rules=["其他生物制剂", "JAK抑制剂"],
        assessment_timing_restrictions=["疗效评估前限制使用救援性糖皮质激素"],
        comparator_summary="匹配安慰剂，每4周皮下注射一次。",
        primary_endpoint="第12周ACR20应答率。",
        key_secondary_endpoints=["第12周DAS28-CRP较基线变化"],
        other_secondary_endpoints=["第24周ACR50和ACR70应答率"],
        exploratory_endpoints=["炎症生物标志物较基线变化"],
        safety_endpoints=["TEAE、SAE及导致停药的AE发生率"],
        aesi_definitions=["严重感染", "超敏反应"],
        study_epochs=["筛选期", "双盲治疗期", "安全性随访期"],
        visit_strategy="筛选、基线，治疗期每4周访视，末次给药后完成安全性随访。",
        estimand_strategy="主要估计目标评价治疗策略下第12周ACR20应答差异。",
        sample_size_strategy="基于预期应答率差异、双侧显著性水平和脱落率估算。",
        statistical_strategy="主要终点采用分层分析并进行多重性控制。",
    )
    payload.update(overrides)
    return MedicalWritingPicosDefinition(**payload)


def _structured_d001_like_rules() -> MedicalWritingInterventionRules:
    """D001-like structured payload: CM dose rule + rescue link to IP hold."""
    return MedicalWritingInterventionRules(
        authority=InterventionRulesAuthority.STRUCTURED,
        ip_regimens=[
            MedicalWritingInterventionIpRegimen(
                regimen_id="ip_main",
                product_name="CMS-D001 50mg 片剂",
                product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
                dose_and_frequency="每日一次口服",
                route="口服",
                treatment_period="治疗期 24 周",
            )
        ],
        ip_adjustment_policy=InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED,
        ip_action_rules=[
            MedicalWritingInterventionIpActionRule(
                rule_id="ip_hold_for_rescue",
                action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                trigger="全身系统性补救治疗启动",
                severity_or_threshold="研究者判断需立即暂停试验药物",
                study_product_action="暂停给药直至研究者评估恢复条件",
                retest_recovery="研究者评估 + ≥5 个半衰期洗脱后恢复",
                approvers=["主要研究者", "申办者医学监查员"],
                wait_period="≥5 个半衰期",
                linked_non_ip_rule_ids=["cm_rescue_systemic"],
            )
        ],
        non_ip_treatment_rules=[
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="bg_mtx",
                rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
                agent_or_category="甲氨蝶呤 7.5-15 mg/周",
                collection_window="基线前 ≥4 周稳定",
            ),
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="cm_folic_acid",
                rule_class=InterventionRulesNonIpRuleClass.ALLOWED_CM,
                policy=InterventionRulesNonIpPolicy.ALLOWED_WITH_TIMING,
                agent_or_category="叶酸 1 mg/日",
                timing_restrictions=["MTX 给药后 24-48 小时"],
            ),
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="cm_rescue_systemic",
                rule_class=InterventionRulesNonIpRuleClass.RESCUE,
                policy=InterventionRulesNonIpPolicy.RESCUE_POLICY,
                agent_or_category="全身系统性糖皮质激素 / 免疫抑制剂",
                # CM dose rule lives ONLY on this non-IP rule; it must never
                # be projected into IP-family fields.
                cm_dose_rule="冲击剂量 ≤ 500 mg/日 甲强龙等效；超过该阈值的剂量调整与方案偏离记录",
            ),
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="cm_prohibited_biologics",
                rule_class=InterventionRulesNonIpRuleClass.PROHIBITED_CM,
                policy=InterventionRulesNonIpPolicy.PROHIBITED,
                agent_or_category="其他生物制剂 / JAK 抑制剂",
            ),
        ],
        cross_object_links=[
            MedicalWritingInterventionCrossObjectLink(
                link_id="link_rescue_hold_ip",
                source_rule_id="cm_rescue_systemic",
                source_kind=InterventionRulesLinkSourceKind.RESCUE,
                target_kind="ip",
                target_rule_id="ip_hold_for_rescue",
                action=InterventionRulesLinkAction.HOLD,
                resume_condition="研究者评估 + ≥5 个半衰期洗脱后书面恢复",
            )
        ],
    )


class MedicalWritingInterventionRulesContractTests(unittest.TestCase):
    """Failure-first tests for the additive structured intervention rules
    contract. Each test targets a single invariant from the frozen contract."""

    # ---------------------- Legacy round-trip ----------------------

    def test_default_authority_is_legacy_and_payloads_round_trip(self):
        """When intervention_rules is omitted, legacy payloads pass through
        validation unchanged and required-field behavior is preserved."""
        picos = _legacy_picos()
        self.assertIsNone(picos.intervention_rules)
        missing = picos.missing_required_fields()
        self.assertNotIn("intervention_dose_regimen", missing)
        self.assertNotIn("required_background_rules", missing)
        self.assertNotIn("allowed_concomitant_rules", missing)
        self.assertNotIn("prohibited_concomitant_rules", missing)
        # round-trip through dict preserves all four legacy fields.
        roundtrip = MedicalWritingPicosDefinition.model_validate(
            picos.model_dump(mode="json")
        )
        self.assertEqual(
            picos.intervention_dose_regimen,
            roundtrip.intervention_dose_regimen,
        )
        self.assertEqual(
            picos.required_background_rules,
            roundtrip.required_background_rules,
        )
        self.assertEqual(
            picos.allowed_concomitant_rules,
            roundtrip.allowed_concomitant_rules,
        )
        self.assertEqual(
            picos.prohibited_concomitant_rules,
            roundtrip.prohibited_concomitant_rules,
        )

    def test_legacy_authority_with_structured_block_keeps_legacy_fields(self):
        """Authority=legacy plus structured block must NOT project into legacy
        fields; the structured block is present but the four legacy fields
        keep whatever value the medical manager provided."""
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.LEGACY,
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_legacy_demo",
                    dose_and_frequency="Q4W",
                )
            ],
        )
        picos = _legacy_picos(
            intervention_dose_regimen="原 legacy 文本",
            allowed_concomitant_rules=["稳定剂量叶酸"],
            intervention_rules=rules,
        )
        projection = picos.project_legacy_intervention_fields()
        self.assertEqual("原 legacy 文本", projection["intervention_dose_regimen"])
        self.assertEqual(["稳定剂量叶酸"], projection["allowed_concomitant_rules"])

    # ---------------------- no_planned_adjustment ----------------------

    def test_no_planned_adjustment_requires_nonblank_statement(self):
        """no_planned_adjustment without a statement must be rejected."""
        with self.assertRaisesRegex(
            ValueError, "nonblank no_planned_adjustment_statement"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_a", dose_and_frequency="Q4W"
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
                ),
                no_planned_adjustment_statement="",
            )

    def test_no_planned_adjustment_accepts_blank_statement_after_strip(self):
        """A whitespace-only statement must also be rejected (after strip)."""
        with self.assertRaisesRegex(
            ValueError, "nonblank no_planned_adjustment_statement"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_a", dose_and_frequency="Q4W"
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
                ),
                no_planned_adjustment_statement="   ",
            )

    def test_no_planned_adjustment_does_not_require_ip_action_rules(self):
        """no_planned_adjustment may coexist with safety interruption /
        permanent discontinuation / taper / follow-up rules. It does NOT
        require at least one ip_action_rule."""
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.STRUCTURED,
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_a", dose_and_frequency="Q4W"
                )
            ],
            ip_adjustment_policy=(
                InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
            ),
            no_planned_adjustment_statement="无计划剂量调整。",
            ip_action_rules=[],
            non_ip_treatment_rules=[
                MedicalWritingInterventionNonIpTreatmentRule(
                    rule_id="bg_stable",
                    rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                    policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
                    agent_or_category="稳定剂量甲氨蝶呤",
                )
            ],
        )
        self.assertEqual(1, len(rules.ip_regimens))
        self.assertEqual(0, len(rules.ip_action_rules))

    # ---------------------- protocol_defined ----------------------

    def test_protocol_defined_requires_at_least_one_ip_action_rule(self):
        """protocol_defined without any ip_action_rules must be rejected."""
        with self.assertRaisesRegex(
            ValueError, "protocol_defined policy requires at least one ip_action_rule"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_a", dose_and_frequency="Q4W"
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[],
            )

    def test_protocol_defined_accepts_multiple_ip_action_rules(self):
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.STRUCTURED,
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_a", dose_and_frequency="Q4W"
                )
            ],
            ip_adjustment_policy=(
                InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
            ),
            ip_action_rules=[
                MedicalWritingInterventionIpActionRule(
                    rule_id="ip_hold",
                    action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                    trigger="ALT > 5x ULN",
                ),
                MedicalWritingInterventionIpActionRule(
                    rule_id="ip_perm_stop",
                    action_kind=InterventionRulesIpActionKind.PERMANENT_DISCONTINUATION,
                    trigger="满足永久停药标准",
                ),
                MedicalWritingInterventionIpActionRule(
                    rule_id="ip_taper",
                    action_kind=InterventionRulesIpActionKind.DISCONTINUATION_TAPER,
                    trigger="研究者评估需逐步减量",
                ),
            ],
        )
        self.assertEqual(3, len(rules.ip_action_rules))

    # ---------------------- ID uniqueness and presence ----------------------

    def test_blank_id_in_any_collection_is_rejected(self):
        # Pydantic's min_length=1 enforces presence at the field level
        # (stricter than the validator's defensive check). Either error path
        # satisfies the contract.
        with self.assertRaises((ValueError, Exception)) as ctx:
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="", dose_and_frequency="Q4W"
                    )
                ],
            )
        message = str(ctx.exception)
        self.assertTrue(
            "regimen_id" in message or "nonblank id" in message,
            f"unexpected error: {message}",
        )

    def test_whitespace_only_id_in_collection_is_rejected(self):
        # Strip-then-check happens inside the model_validator; the field
        # accepts the whitespace but the contract rejects it.
        with self.assertRaisesRegex(
            ValueError, "must carry a nonblank id"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="   ", dose_and_frequency="Q4W"
                    )
                ],
            )

    def test_duplicate_id_across_collections_is_rejected(self):
        """An id used in two collections must be rejected."""
        with self.assertRaisesRegex(
            ValueError, "ids must be unique across all collections"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="dup", dose_and_frequency="Q4W"
                    )
                ],
                non_ip_treatment_rules=[
                    MedicalWritingInterventionNonIpTreatmentRule(
                        rule_id="dup",
                        rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                        policy=InterventionRulesNonIpPolicy.ALLOWED,
                        agent_or_category="MTX",
                    )
                ],
            )

    def test_duplicate_id_within_ip_action_rules_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "ids must be unique across all collections"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_main",
                        dose_and_frequency="Q4W",
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_a",
                        action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                    ),
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_a",
                        action_kind=InterventionRulesIpActionKind.RESUME,
                    ),
                ],
            )

    # ---------------------- Cross-object link integrity ----------------------

    def test_link_source_rule_id_must_reference_existing_non_ip_rule(self):
        """A link pointing at a non-existent non-IP source rule must be rejected."""
        with self.assertRaisesRegex(
            ValueError, "must reference an existing non_ip_treatment_rules rule"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_main", dose_and_frequency="Q4W"
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_hold",
                        action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                    )
                ],
                non_ip_treatment_rules=[
                    MedicalWritingInterventionNonIpTreatmentRule(
                        rule_id="bg_mtx",
                        rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                        policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
                        agent_or_category="MTX",
                    )
                ],
                cross_object_links=[
                    MedicalWritingInterventionCrossObjectLink(
                        link_id="l1",
                        source_rule_id="missing_rule",
                        source_kind=InterventionRulesLinkSourceKind.CM,
                        target_kind="ip",
                        target_rule_id="ip_hold",
                        action=InterventionRulesLinkAction.HOLD,
                    )
                ],
            )

    def test_link_target_rule_id_when_nonblank_must_reference_existing_ip_action(self):
        with self.assertRaisesRegex(
            ValueError, "must reference an existing ip_action_rule when nonblank"
        ):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_main", dose_and_frequency="Q4W"
                    )
                ],
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_hold",
                        action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                    )
                ],
                non_ip_treatment_rules=[
                    MedicalWritingInterventionNonIpTreatmentRule(
                        rule_id="cm_x",
                        rule_class=InterventionRulesNonIpRuleClass.ALLOWED_CM,
                        policy=InterventionRulesNonIpPolicy.ALLOWED,
                        agent_or_category="X",
                    )
                ],
                cross_object_links=[
                    MedicalWritingInterventionCrossObjectLink(
                        link_id="l1",
                        source_rule_id="cm_x",
                        source_kind=InterventionRulesLinkSourceKind.CM,
                        target_kind="ip",
                        target_rule_id="ip_does_not_exist",
                        action=InterventionRulesLinkAction.HOLD,
                    )
                ],
            )

    def test_link_with_blank_target_rule_id_is_allowed(self):
        """An empty target_rule_id is allowed (link documents source-side policy
        without requiring an IP-side reference)."""
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.STRUCTURED,
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_main", dose_and_frequency="Q4W"
                )
            ],
            ip_adjustment_policy=(
                InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
            ),
            ip_action_rules=[
                MedicalWritingInterventionIpActionRule(
                    rule_id="ip_hold",
                    action_kind=InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
                )
            ],
            non_ip_treatment_rules=[
                MedicalWritingInterventionNonIpTreatmentRule(
                    rule_id="cm_rescue",
                    rule_class=InterventionRulesNonIpRuleClass.RESCUE,
                    policy=InterventionRulesNonIpPolicy.RESCUE_POLICY,
                    agent_or_category="全身系统性糖皮质激素",
                )
            ],
            cross_object_links=[
                MedicalWritingInterventionCrossObjectLink(
                    link_id="l1",
                    source_rule_id="cm_rescue",
                    source_kind=InterventionRulesLinkSourceKind.RESCUE,
                    target_kind="ip",
                    target_rule_id="",
                    action=InterventionRulesLinkAction.NO_AUTO_IP_ACTION,
                )
            ],
        )
        self.assertEqual(1, len(rules.cross_object_links))

    def test_ip_action_linked_non_ip_ids_must_exist(self):
        with self.assertRaisesRegex(ValueError, "linked_non_ip_rule_ids"):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_hold",
                        action_kind=(
                            InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION
                        ),
                        linked_non_ip_rule_ids=["missing_rescue_rule"],
                    )
                ],
            )

    def test_cross_object_source_kind_must_match_non_ip_rule_class(self):
        with self.assertRaisesRegex(ValueError, "source_kind must match"):
            MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.STRUCTURED,
                ip_adjustment_policy=(
                    InterventionRulesIpAdjustmentPolicy.PROTOCOL_DEFINED
                ),
                ip_action_rules=[
                    MedicalWritingInterventionIpActionRule(
                        rule_id="ip_hold",
                        action_kind=(
                            InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION
                        ),
                    )
                ],
                non_ip_treatment_rules=[
                    MedicalWritingInterventionNonIpTreatmentRule(
                        rule_id="rescue_rule",
                        rule_class=InterventionRulesNonIpRuleClass.RESCUE,
                        policy=InterventionRulesNonIpPolicy.RESCUE_POLICY,
                    )
                ],
                cross_object_links=[
                    MedicalWritingInterventionCrossObjectLink(
                        link_id="link_1",
                        source_rule_id="rescue_rule",
                        source_kind=InterventionRulesLinkSourceKind.CM,
                        target_rule_id="ip_hold",
                        action=InterventionRulesLinkAction.HOLD,
                    )
                ],
            )

    # ---------------------- Legacy projection under structured authority -----

    def test_structured_authority_projects_regimens_and_non_ip_rules(self):
        """When authority is structured, ip_regimens and non_ip rules are
        projected into the four legacy fields deterministically."""
        rules = _structured_d001_like_rules()
        picos = _legacy_picos(
            intervention_rules=rules,
            # Provide stale legacy content to prove the projection overrides.
            intervention_dose_regimen="原 legacy 文本，不应保留",
            required_background_rules=["原 legacy background"],
            allowed_concomitant_rules=["原 legacy allowed"],
            prohibited_concomitant_rules=["原 legacy prohibited"],
        )
        projection = picos.project_legacy_intervention_fields()
        # Regimen text contains the IP product + dose + route + period.
        self.assertIn("CMS-D001 50mg 片剂", projection["intervention_dose_regimen"])
        self.assertIn("每日一次口服", projection["intervention_dose_regimen"])
        self.assertIn("口服", projection["intervention_dose_regimen"])
        self.assertIn("治疗期 24 周", projection["intervention_dose_regimen"])
        # protocol_defined branch appends IP action rule rendering.
        self.assertIn("剂量调整", projection["intervention_dose_regimen"])
        # rule_id lives on the canonical structured block; the projection
        # surfaces action_kind + trigger + study_product_action for
        # backward-compatible consumers.
        self.assertIn(
            "[temporary_interruption]",
            projection["intervention_dose_regimen"],
        )
        self.assertIn(
            "全身系统性补救治疗启动", projection["intervention_dose_regimen"]
        )
        self.assertIn(
            "暂停给药直至研究者评估恢复条件",
            projection["intervention_dose_regimen"],
        )
        # Background rule (bg_mtx) projects into required_background_rules.
        self.assertEqual(
            ["甲氨蝶呤 7.5-15 mg/周（基线前 ≥4 周稳定；策略=allowed_if_stable）"],
            projection["required_background_rules"],
        )
        # Allowed CM (cm_folic_acid) projects into allowed_concomitant_rules.
        self.assertEqual(
            ["叶酸 1 mg/日（策略=allowed_with_timing；时序=MTX 给药后 24-48 小时）"],
            projection["allowed_concomitant_rules"],
        )
        # Prohibited CM (cm_prohibited_biologics) projects into prohibited.
        self.assertEqual(
            ["其他生物制剂 / JAK 抑制剂（策略=prohibited）"],
            projection["prohibited_concomitant_rules"],
        )
        # Rescue and other_non_investigational do NOT project into any of the
        # four legacy fields. They live only on the structured block and
        # surface via non-investigational-impact routes.
        rescue_text = "全身系统性糖皮质激素"
        self.assertNotIn(rescue_text, projection["intervention_dose_regimen"])
        self.assertNotIn(rescue_text, projection["required_background_rules"])
        self.assertNotIn(rescue_text, projection["allowed_concomitant_rules"])
        self.assertNotIn(rescue_text, projection["prohibited_concomitant_rules"])

    def test_structured_authority_d001_like_separates_cm_dose_from_ip_actions(self):
        """The D001-like invariant: a CM dose rule lives only on the non-IP
        rule; rescue -> IP hold link survives; the IP action rules never pick
        up the CM dose text; rescue rules do NOT project into the IP-family
        legacy field."""
        rules = _structured_d001_like_rules()
        picos = _legacy_picos(intervention_rules=rules)
        projection = picos.project_legacy_intervention_fields()

        # 1. The rescue rule's agent_or_category must NOT leak into the IP-
        #    family legacy field. Rescue rules project only into structured
        #    non-investigational consumers (handled by the frontend routing
        #    on picos.intervention_rules), never into the CM-family legacy
        #    fields, and never into the IP-family legacy field.
        rescue_text = "全身系统性糖皮质激素 / 免疫抑制剂"
        for legacy_field in (
            "intervention_dose_regimen",
            "required_background_rules",
            "allowed_concomitant_rules",
            "prohibited_concomitant_rules",
        ):
            value = projection[legacy_field]
            value_str = "".join(value) if isinstance(value, list) else value
            self.assertNotIn(
                rescue_text,
                value_str,
                f"rescue rule leaked into {legacy_field}: {value_str}",
            )

        # 2. The CM dose rule content (rescue's cm_dose_rule) must NOT
        #    surface in intervention_dose_regimen (the IP-family field).
        dose_text = "冲击剂量 ≤ 500 mg/日 甲强龙等效"
        self.assertNotIn(dose_text, projection["intervention_dose_regimen"])

        # 3. The cross-object link is preserved verbatim in the structured
        #    block; the projection does not need to surface it because the
        #    structured block IS the source of truth.
        link = rules.cross_object_links[0]
        self.assertEqual("cm_rescue_systemic", link.source_rule_id)
        self.assertEqual("ip_hold_for_rescue", link.target_rule_id)
        self.assertEqual(InterventionRulesLinkAction.HOLD, link.action)

        # 4. The IP action rule never references the CM dose rule's content.
        ip_action_rule = rules.ip_action_rules[0]
        self.assertEqual(
            InterventionRulesIpActionKind.TEMPORARY_INTERRUPTION,
            ip_action_rule.action_kind,
        )
        self.assertNotIn(dose_text, ip_action_rule.trigger)
        self.assertNotIn(dose_text, ip_action_rule.study_product_action)
        self.assertNotIn(dose_text, ip_action_rule.notes)

        # 5. The CM dose rule content lives on the rescue rule only.
        rescue_rule = next(
            rule
            for rule in rules.non_ip_treatment_rules
            if rule.rule_id == "cm_rescue_systemic"
        )
        self.assertIn(dose_text, rescue_rule.cm_dose_rule)
        self.assertEqual(
            InterventionRulesNonIpRuleClass.RESCUE, rescue_rule.rule_class
        )

    def test_structured_authority_no_planned_adjustment_projects_statement_only(self):
        """When policy is no_planned_adjustment and statement is nonblank,
        the IP family projection must surface the statement, and no IP action
        rules are required."""
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.STRUCTURED,
            ip_regimens=[
                MedicalWritingInterventionIpRegimen(
                    regimen_id="ip_main",
                    dose_and_frequency="每 4 周一次",
                    route="皮下注射",
                )
            ],
            ip_adjustment_policy=(
                InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
            ),
            no_planned_adjustment_statement="本试验不预设常规剂量调整。",
            non_ip_treatment_rules=[
                MedicalWritingInterventionNonIpTreatmentRule(
                    rule_id="bg_stable",
                    rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                    policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
                    agent_or_category="稳定剂量甲氨蝶呤",
                )
            ],
        )
        picos = _legacy_picos(intervention_rules=rules)
        projection = picos.project_legacy_intervention_fields()
        self.assertIn(
            "本试验不预设常规剂量调整。",
            projection["intervention_dose_regimen"],
        )
        # ip_action_rules is empty, so no "剂量调整：" ip-action rendering.
        self.assertNotIn(
            "[temporary_interruption]", projection["intervention_dose_regimen"]
        )
        # Background projects into the legacy field. Policy is
        # ALLOWED_IF_STABLE so the policy bit shows.
        self.assertEqual(
            ["稳定剂量甲氨蝶呤（策略=allowed_if_stable）"],
            projection["required_background_rules"],
        )

    def test_no_planned_adjustment_projection_keeps_safety_stop_rules(self):
        rules = MedicalWritingInterventionRules(
            authority=InterventionRulesAuthority.STRUCTURED,
            ip_adjustment_policy=(
                InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
            ),
            no_planned_adjustment_statement="本试验不预设常规剂量调整。",
            ip_action_rules=[
                MedicalWritingInterventionIpActionRule(
                    rule_id="ip_stop",
                    action_kind=(
                        InterventionRulesIpActionKind.PERMANENT_DISCONTINUATION
                    ),
                    trigger="发生方案规定的永久停药条件",
                    study_product_action="永久停止试验用药品",
                )
            ],
        )
        projection = _legacy_picos(
            intervention_rules=rules
        ).project_legacy_intervention_fields()
        self.assertIn(
            "本试验不预设常规剂量调整。",
            projection["intervention_dose_regimen"],
        )
        self.assertIn(
            "永久停止试验用药品",
            projection["intervention_dose_regimen"],
        )

    # ---------------------- End-to-end via journey service -------------------

    def test_journey_commit_with_structured_authority_applies_projection(self):
        """End-to-end: structured authority flows through commit_stage and the
        resulting StudyDefinition.picos carries the projected legacy fields,
        not the user-supplied stale text."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "authoring_journey.sqlite3"
            )
            project_id = "proj_ir_contract_structured"
            framed = service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=_complete_framing(),
                    actor="medical_manager_test",
                    idempotency_key="ir-create-structured",
                ),
            )
            rules = _structured_d001_like_rules()
            picos = _legacy_picos(
                intervention_rules=rules,
                intervention_dose_regimen="stale legacy regimen text",
                required_background_rules=["stale bg"],
                allowed_concomitant_rules=["stale allowed"],
                prohibited_concomitant_rules=["stale prohibited"],
            )
            designed = service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=framed.revision,
                    stage="picos",
                    picos=picos,
                    actor="medical_manager_test",
                    idempotency_key="ir-commit-structured",
                ),
            )
            self.assertEqual("corpus_not_ready", designed.status)
            persisted = designed.study_definition.picos
            self.assertIn("CMS-D001 50mg 片剂", persisted.intervention_dose_regimen)
            self.assertIn(
                "剂量调整", persisted.intervention_dose_regimen
            )
            # Background rule (bg_mtx) projects into required_background_rules.
            self.assertEqual(
                ["甲氨蝶呤 7.5-15 mg/周（基线前 ≥4 周稳定；策略=allowed_if_stable）"],
                persisted.required_background_rules,
            )
            # Allowed CM (cm_folic_acid) projects into allowed_concomitant_rules.
            self.assertEqual(
                ["叶酸 1 mg/日（策略=allowed_with_timing；时序=MTX 给药后 24-48 小时）"],
                persisted.allowed_concomitant_rules,
            )
            # Prohibited CM (cm_prohibited_biologics) projects into prohibited.
            self.assertEqual(
                ["其他生物制剂 / JAK 抑制剂（策略=prohibited）"],
                persisted.prohibited_concomitant_rules,
            )
            # Stale text was overridden by projection.
            self.assertNotIn("stale", persisted.intervention_dose_regimen)
            self.assertNotEqual(
                ["stale bg"], persisted.required_background_rules
            )

            # Round-trip persistence: reload and confirm projection survives.
            reloaded = MedicalWritingAuthoringJourneyService(
                service.db_path
            ).get(project_id)
            persisted_reloaded = reloaded.study_definition.picos
            self.assertIn(
                "CMS-D001 50mg 片剂",
                persisted_reloaded.intervention_dose_regimen,
            )
            self.assertEqual(
                ["甲氨蝶呤 7.5-15 mg/周（基线前 ≥4 周稳定；策略=allowed_if_stable）"],
                persisted_reloaded.required_background_rules,
            )
        finally:
            tmpdir.cleanup()

    def test_journey_legacy_authority_does_not_apply_projection(self):
        """When authority is legacy, the user's legacy text must round-trip
        unchanged even if a structured block is attached (structured block is
        present but legacy text wins)."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "authoring_journey.sqlite3"
            )
            project_id = "proj_ir_contract_legacy"
            framed = service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=_complete_framing(),
                    actor="medical_manager_test",
                    idempotency_key="ir-create-legacy",
                ),
            )
            legacy_rules = MedicalWritingInterventionRules(
                authority=InterventionRulesAuthority.LEGACY,
                ip_regimens=[
                    MedicalWritingInterventionIpRegimen(
                        regimen_id="ip_main",
                        dose_and_frequency="Q4W",
                    )
                ],
            )
            picos = _legacy_picos(
                intervention_rules=legacy_rules,
                intervention_dose_regimen="legacy 用户编辑文本",
                required_background_rules=["legacy bg"],
            )
            designed = service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=framed.revision,
                    stage="picos",
                    picos=picos,
                    actor="medical_manager_test",
                    idempotency_key="ir-commit-legacy",
                ),
            )
            persisted = designed.study_definition.picos
            self.assertEqual(
                "legacy 用户编辑文本",
                persisted.intervention_dose_regimen,
            )
            self.assertEqual(["legacy bg"], persisted.required_background_rules)
        finally:
            tmpdir.cleanup()

    # ---------------------- Impact routing ---------------------------------

    def test_impact_preview_routes_picos_intervention_rules_to_required_buckets(self):
        """When picos.intervention_rules changes, impact_preview must route
        the change to dose_modification_rules, non_investigational_interventions
        and concomitant_therapy_rules while leaving the existing legacy
        routes intact."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "authoring_journey.sqlite3"
            )
            project_id = "proj_ir_impact"
            framed = service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=_complete_framing(),
                    actor="medical_manager_test",
                    idempotency_key="ir-create-impact",
                ),
            )
            designed = service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=framed.revision,
                    stage="picos",
                    picos=_legacy_picos(),
                    actor="medical_manager_test",
                    idempotency_key="ir-commit-impact-picos",
                ),
            )
            # Legacy round-trip: changing only intervention_dose_regimen keeps
            # the existing route to dose_modification_rules and
            # intervention_sections.
            legacy_changed = _legacy_picos(
                intervention_dose_regimen="每 4 周给药一次，持续 24 周（修订）。"
            )
            legacy_preview = service.impact_preview(
                project_id,
                MedicalWritingJourneyImpactPreviewRequest(
                    expected_revision=designed.revision,
                    stage="picos",
                    picos=legacy_changed,
                ),
            )
            self.assertIn(
                "picos.intervention_dose_regimen", legacy_preview.changed_fields
            )
            self.assertIn(
                "dose_modification_rules", legacy_preview.affected_dependents
            )
            self.assertIn(
                "intervention_sections", legacy_preview.affected_dependents
            )

            # Now change intervention_rules: it must route to all 3 buckets.
            structured_changed = _legacy_picos(
                intervention_rules=MedicalWritingInterventionRules(
                    authority=InterventionRulesAuthority.STRUCTURED,
                    ip_regimens=[
                        MedicalWritingInterventionIpRegimen(
                            regimen_id="ip_main",
                            dose_and_frequency="Q4W",
                        )
                    ],
                    ip_adjustment_policy=(
                        InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
                    ),
                    no_planned_adjustment_statement="无计划剂量调整。",
                    non_ip_treatment_rules=[
                        MedicalWritingInterventionNonIpTreatmentRule(
                            rule_id="bg_mtx",
                            rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                            policy=InterventionRulesNonIpPolicy.ALLOWED_IF_STABLE,
                            agent_or_category="MTX",
                        ),
                        MedicalWritingInterventionNonIpTreatmentRule(
                            rule_id="cm_folic_acid",
                            rule_class=InterventionRulesNonIpRuleClass.ALLOWED_CM,
                            policy=InterventionRulesNonIpPolicy.ALLOWED_WITH_TIMING,
                            agent_or_category="叶酸 1 mg/日",
                        ),
                    ],
                ),
            )
            structured_preview = service.impact_preview(
                project_id,
                MedicalWritingJourneyImpactPreviewRequest(
                    expected_revision=designed.revision,
                    stage="picos",
                    picos=structured_changed,
                ),
            )
            self.assertIn(
                "picos.intervention_rules", structured_preview.changed_fields
            )
            for bucket in (
                "dose_modification_rules",
                "non_investigational_interventions",
                "concomitant_therapy_rules",
                "intervention_sections",
                "protocol_synopsis",
                "study_schema",
                "schedule_of_activities",
            ):
                self.assertIn(
                    bucket,
                    structured_preview.affected_dependents,
                    f"missing route for {bucket}",
                )
        finally:
            tmpdir.cleanup()

    def test_journey_picos_draft_preserves_structured_block(self):
        """save_stage_draft must keep the structured block intact in the draft
        so the medical manager can resume editing without losing data."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "authoring_journey.sqlite3"
            )
            project_id = "proj_ir_draft"
            framed = service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=_complete_framing(),
                    actor="medical_manager_test",
                    idempotency_key="ir-create-draft",
                ),
            )
            rules = _structured_d001_like_rules()
            draft_picos = _legacy_picos(intervention_rules=rules)
            # Mark incomplete by clearing required_background_rules.
            draft_picos = draft_picos.model_copy(
                update={"primary_endpoint": ""}
            )
            saved = service.save_stage_draft(
                project_id,
                MedicalWritingAuthoringJourneyDraftSaveRequest(
                    expected_revision=framed.revision,
                    stage="picos",
                    picos=draft_picos,
                    actor="medical_manager_test",
                    idempotency_key="ir-save-draft",
                ),
            )
            self.assertIsNotNone(saved.picos_draft)
            persisted_rules = saved.picos_draft.picos.intervention_rules
            self.assertIsNotNone(persisted_rules)
            self.assertEqual(
                InterventionRulesAuthority.STRUCTURED, persisted_rules.authority
            )
            self.assertEqual(
                4, len(persisted_rules.non_ip_treatment_rules)
            )
            self.assertEqual(
                1, len(persisted_rules.cross_object_links)
            )
        finally:
            tmpdir.cleanup()

    def test_study_definition_binding_uses_structured_compatibility_projection(self):
        """Structured authority must not make a complete journey unbindable.

        The authoring journey retains the medical manager's legacy compatibility
        text, while StudyDefinition stores the deterministic structured
        projection. Binding therefore compares the canonical projection rather
        than the two raw objects.
        """
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "authoring_journey.sqlite3"
            )
            project_id = "proj_ir_definition_binding"
            framed = service.create(
                project_id,
                MedicalWritingAuthoringJourneyCreateRequest(
                    framing=_complete_framing(),
                    actor="medical_manager_test",
                    idempotency_key="ir-create-definition-binding",
                ),
            )
            committed = service.commit_stage(
                project_id,
                MedicalWritingAuthoringJourneyCommitRequest(
                    expected_revision=framed.revision,
                    stage="picos",
                    picos=_legacy_picos(
                        intervention_rules=_structured_d001_like_rules()
                    ),
                    actor="medical_manager_test",
                    idempotency_key="ir-commit-definition-binding",
                ),
            )
            definition = committed.study_definition
            self.assertIsNotNone(definition)
            self.assertNotEqual(
                committed.picos.intervention_dose_regimen,
                definition.picos.intervention_dose_regimen,
            )

            bound = service.require_study_definition_binding(
                project_id,
                definition_id=definition.definition_id,
                revision=definition.revision,
                state_sha256=definition.state_sha256,
            )

            self.assertEqual(definition.state_sha256, bound.state_sha256)
            self.assertEqual(
                committed.picos.project_legacy_intervention_fields()[
                    "intervention_dose_regimen"
                ],
                bound.picos.intervention_dose_regimen,
            )
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
