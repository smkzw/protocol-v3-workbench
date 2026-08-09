from __future__ import annotations

from datetime import datetime, timezone
import unittest

from packages.contracts.workbench_contracts.models import (
    MonitoringRiskDispositionKind,
    RiskCase,
    RiskSeverity,
    RiskStatus,
    SubjectTrendPoint,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
)


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


class MonitoringRiskContractV2Tests(unittest.TestCase):
    def test_risk_exposes_stable_cross_batch_key_and_batch_bound_instance(self) -> None:
        risk = RiskCase(
            risk_id="legacy_risk_001",
            risk_key="riskkey_proj_subject_rule",
            risk_instance_id="riskinst_batch003_001",
            project_id="proj_mgk10_sar_demo",
            module="medical_monitoring",
            risk_type="AE/MH漏报",
            title="眼部异常与AE记录不一致",
            subject_id="06021",
            site_id="06",
            scope_type="subject",
            scope_id="06021",
            severity=RiskSeverity.MEDIUM,
            status=RiskStatus.IN_REVIEW,
            source_batch_id="batch_003",
            rule_id="AE_MH_RECONCILIATION",
            evidence_span_ids=["listing:LB:row:21"],
            rationale="眼部异常记录与AE表不一致。",
            recommended_action="复核AE与MH记录。",
            created_at=NOW,
        )

        payload = risk.model_dump(mode="json")

        self.assertEqual("riskkey_proj_subject_rule", payload["risk_key"])
        self.assertEqual("riskinst_batch003_001", payload["risk_instance_id"])
        self.assertEqual("subject", payload["scope_type"])
        self.assertEqual("06021", payload["scope_id"])
        self.assertEqual("legacy_risk_001", payload["risk_id"])

    def test_legacy_risk_derives_identity_and_scope_without_losing_compatibility(self) -> None:
        risk = RiskCase(
            risk_id="legacy_risk_002",
            project_id="proj_rux_03_002",
            module="medical_monitoring",
            risk_type="实验室异常",
            title="ALT升高需复核",
            subject_id="S01001",
            site_id="S01",
            severity=RiskSeverity.HIGH,
            status=RiskStatus.ACTION_REQUIRED,
            source_batch_id="rux_batch_20250612",
            rule_id="RUX-LAB-ALT-AST-GT3ULN-INTERRUPT",
            evidence_span_ids=["listing:LBCHEM:row:12"],
            rationale="ALT超过方案阈值。",
            recommended_action="复核给药调整与AE。",
            created_at=NOW,
        )

        self.assertEqual("legacy_risk_002", risk.risk_key)
        self.assertEqual("legacy_risk_002", risk.risk_instance_id)
        self.assertEqual("subject", risk.scope_type)
        self.assertEqual("S01001", risk.scope_id)

    def test_risk_keeps_medical_inspection_ctcae_action_and_confidence_dimensions_separate(self) -> None:
        risk = RiskCase(
            risk_id="risk_003",
            risk_key="riskkey_alt",
            risk_instance_id="riskinst_alt_batch003",
            project_id="proj_rux_03_002",
            module="medical_monitoring",
            risk_type="实验室异常未解释",
            primary_category="safety_ae_mh",
            tags=["safety_pv", "cfdi", "aesi"],
            title="ALT升高且未见医学解释",
            subject_id="S01001",
            site_id="S01",
            severity=RiskSeverity.HIGH,
            inspection_priority="critical",
            ctcae_grade=2,
            action_priority="within_24h",
            confidence=0.86,
            status=RiskStatus.ACTION_REQUIRED,
            source_batch_id="batch_003",
            rule_id="ALT_UNEXPLAINED",
            rationale="ALT升高且未见AE或合并用药解释。",
            recommended_action="复核AE、CM和试验药物变更。",
            created_at=NOW,
        )

        self.assertEqual(RiskSeverity.HIGH, risk.severity)
        self.assertEqual("critical", risk.inspection_priority)
        self.assertEqual(2, risk.ctcae_grade)
        self.assertEqual("within_24h", risk.action_priority)
        self.assertEqual(0.86, risk.confidence)
        self.assertEqual(["safety_pv", "cfdi", "aesi"], risk.tags)

    def test_risk_instance_binds_source_rule_engine_and_batch_delta(self) -> None:
        risk = RiskCase(
            risk_id="risk_004",
            risk_key="riskkey_washout",
            risk_instance_id="riskinst_washout_batch004",
            project_id="proj_mgk10_sar_demo",
            module="medical_monitoring",
            risk_type="禁限用药/洗脱违规",
            title="随机前抗组胺药洗脱不足",
            subject_id="10008",
            site_id="10",
            severity=RiskSeverity.HIGH,
            status=RiskStatus.ACTION_REQUIRED,
            source_batch_id="batch_004",
            source_revision="monsrcv_batch004_protocol_v2_1",
            rule_profile_revision="ruleprofile_sar_v2_1_r3",
            engine_version="monitoring-risk-engine-v0.2",
            batch_delta="requires_rereview",
            rule_id="WASHOUT_ANTIHISTAMINE_4D",
            evidence_span_ids=["listing:CM:row:88", "protocol:section:6.5"],
            rationale="来源映射变化后需重新复核洗脱窗口。",
            recommended_action="重新核对CM末次用药与随机日期。",
            created_at=NOW,
        )

        self.assertEqual("monsrcv_batch004_protocol_v2_1", risk.source_revision)
        self.assertEqual("ruleprofile_sar_v2_1_r3", risk.rule_profile_revision)
        self.assertEqual("monitoring-risk-engine-v0.2", risk.engine_version)
        self.assertEqual("requires_rereview", risk.batch_delta)

    def test_trend_point_can_link_back_to_canonical_risk_instances(self) -> None:
        point = SubjectTrendPoint(
            point_id="pt_alt_w1",
            visit_code="W1",
            visit_label="第1周",
            assessment_date="2026-07-13",
            study_day=8,
            value=42,
            reference_high=40,
            normality="high",
            risk_flag=True,
            source_domain="LB",
            source_record_id="LB-10008-ALT-W1",
            source_locator="listing:LB:row:42",
            related_risk_ids=["riskinst_alt_batch003"],
        )

        self.assertEqual(["riskinst_alt_batch003"], point.related_risk_ids)

    def test_disposition_kind_is_separate_from_workflow_action(self) -> None:
        request = RuxRiskDispositionActionRequest(
            action=RuxRiskDispositionAction.REVIEWED,
            disposition_kind=MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION,
            comment="需与Safety/PV协作复核，但风险状态仍由医学监查拥有。",
            expected_source_version="source-v1",
        )

        self.assertEqual(RuxRiskDispositionAction.REVIEWED, request.action)
        self.assertEqual(
            MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION,
            request.disposition_kind,
        )


if __name__ == "__main__":
    unittest.main()
