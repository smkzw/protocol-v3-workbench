from __future__ import annotations

import json
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import services.api.app.main as main_module  # noqa: E402
from services.api.app.main import app  # noqa: E402
from services.api.app.monitoring_identity_authorization import MonitoringRole  # noqa: E402
from services.api.app.monitoring_runtime_principal import (  # noqa: E402
    MonitoringAuthenticatedPrincipal,
)

try:
    from services.api.app.rux_monitoring_service import RuxMonitoringService
except Exception as exc:  # pragma: no cover - exercised as the initial TDD red state.
    RuxMonitoringService = None
    RUX_SERVICE_IMPORT_ERROR = exc
else:
    RUX_SERVICE_IMPORT_ERROR = None


LISTING_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/准备阶段/"
    "RUX-03-002_列表_数据集_Excel_20250612_处理后.xlsx"
)
PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/"
    "10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/"
    "磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)


class RuxMonitoringServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if RuxMonitoringService is None:
            cls.service = None
            return
        cls.service = RuxMonitoringService(listing_path=LISTING_PATH, protocol_path=PROTOCOL_PATH)

    def _service(self):
        if self.service is None:
            self.fail(f"RuxMonitoringService must exist as an additive real-data service: {RUX_SERVICE_IMPORT_ERROR}")
        return self.service

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="rux-monitoring-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="rux-monitoring-test-session",
            directory_revision="rux-monitoring-test-v1",
            verification_ref_sha256="a" * 64,
        )

    class _PrincipalMiddleware:
        def __init__(self, application, principal):
            self.application = application
            self.principal = principal

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {})["monitoring_principal"] = self.principal
            await self.application(scope, receive, send)

    def _client_with_principal(self):
        return TestClient(self._PrincipalMiddleware(app, self._principal()))

    def _client_with_current_rux_snapshot(self):
        client = self._client_with_principal()
        response = client.post(
            "/api/projects/proj_rux_03_002/modules/medical-monitoring/runs"
        )
        self.assertIn(response.status_code, {200, 201}, response.text)
        payload = response.json()
        self.assertIn(
            payload["status"],
            {"snapshot_generated", "current_snapshot_reused"},
        )
        self.assertGreaterEqual(payload["risk_count"], 3)
        return client

    def test_protocol_registry_extracts_table4_and_table7_rules(self):
        registry = self._service().protocol_rule_registry()

        table4_ids = {rule["rule_id"] for rule in registry["table4"]}
        self.assertIn("RUX-LAB-ALT-AST-GT3ULN-INTERRUPT", table4_ids)
        self.assertIn("RUX-LAB-ANC-LT1_5-INTERRUPT", table4_ids)
        self.assertIn("RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE", table4_ids)

        table7_ids = {rule["rule_id"] for rule in registry["table7"]}
        self.assertIn("RUX-ICE-PROHIBITED-CONMED-NONRESPONSE", table7_ids)
        self.assertIn("RUX-ICE-POOR-EFFICACY-DISCONTINUATION-NONRESPONSE", table7_ids)
        self.assertIn("RUX-ICE-NON_EFFICACY-DISCONTINUATION-MI", table7_ids)

        alt_rule = next(rule for rule in registry["table4"] if rule["rule_id"] == "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT")
        self.assertEqual("docx:table:4:row:2", alt_rule["source_locator"])
        self.assertIn("中断", alt_rule["action"])

    def test_lab_rules_detect_real_alt_and_anc_anchors_with_source_locators(self):
        s01017 = self._service().evaluate_subject_risks("proj_rux_03_002", "S01017")
        alt_rules = {risk.rule_id: risk for risk in s01017}
        self.assertIn("RUX-LAB-ALT-AST-GT3ULN-INTERRUPT", alt_rules)
        self.assertEqual(
            "laboratory_abnormality",
            alt_rules[
                "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT"
            ].primary_category,
        )
        self.assertIn("RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE", alt_rules)
        self.assertTrue(any("row:1849" in ref for ref in alt_rules["RUX-LAB-ALT-AST-GT3ULN-INTERRUPT"].evidence_span_ids))
        self.assertTrue(any("docx:table:4:row:2" in ref for ref in alt_rules["RUX-LAB-ALT-AST-GT3ULN-INTERRUPT"].evidence_span_ids))
        self.assertTrue(any("row:1863" in ref for ref in alt_rules["RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE"].evidence_span_ids))
        self.assertTrue(any("docx:table:4:row:7" in ref for ref in alt_rules["RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE"].evidence_span_ids))

        s01003 = self._service().evaluate_subject_risks("proj_rux_03_002", "S01003")
        anc_rule = next(risk for risk in s01003 if risk.rule_id == "RUX-LAB-ANC-LT1_5-INTERRUPT")
        self.assertTrue(any("LBHEMA--实验室检查-血常规" in ref and "row:231" in ref for ref in anc_rule.evidence_span_ids))
        self.assertTrue(any("docx:table:4:row:4" in ref for ref in anc_rule.evidence_span_ids))

    def test_real_rux_risks_use_stable_keys_and_source_bound_instances(self):
        risks = self._service().evaluate_subject_risks("proj_rux_03_002", "S01017")
        risk = next(item for item in risks if item.rule_id == "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT")

        self.assertTrue(risk.risk_key.startswith("riskkey_"))
        self.assertTrue(risk.risk_instance_id.startswith("riskinst_"))
        self.assertNotEqual(risk.risk_key, risk.risk_instance_id)
        self.assertEqual("subject", risk.scope_type)
        self.assertEqual("S01017", risk.scope_id)
        self.assertTrue(risk.source_revision.startswith("monsrcv_"))
        self.assertEqual("rux-protocol-v1.3-rules-v1", risk.rule_profile_revision)
        self.assertEqual("rux-monitoring-risk-v0.5", risk.engine_version)
        self.assertEqual("rux-protocol-v1.3-rules-v1", self._service().risk_profile_revision())
        self.assertEqual("rux-monitoring-risk-v0.5", self._service().risk_engine_version())

    def test_rux_timeline_and_profile_points_link_to_the_same_risk_instance(self):
        risks = self._service().evaluate_subject_risks("proj_rux_03_002", "S01017")
        risk = next(item for item in risks if item.rule_id == "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT")
        profile = self._service().subject_monitoring("proj_rux_03_002", "S01017")

        linked_events = [event for event in profile.timeline if risk.risk_instance_id in event.related_risk_ids]
        linked_points = [
            point
            for metric in profile.efficacy_trends + profile.safety_trends
            for point in metric.points
            if risk.risk_instance_id in point.related_risk_ids
        ]

        self.assertTrue(any("row:1849" in event.source_locator for event in linked_events))
        self.assertTrue(any("row:1849" in point.source_locator for point in linked_points))

    def test_batch_context_changes_instance_identity_but_not_stable_risk_key(self):
        first = next(
            item
            for item in self._service().evaluate_subject_risks("proj_rux_03_002", "S01017")
            if item.rule_id == "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT"
        )
        next_batch_service = RuxMonitoringService(
            listing_path=LISTING_PATH,
            protocol_path=PROTOCOL_PATH,
            source_batch_id="rux_03_002_listing_20250619",
        )
        second = next(
            item
            for item in next_batch_service.evaluate_subject_risks("proj_rux_03_002", "S01017")
            if item.rule_id == "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT"
        )

        self.assertEqual(first.risk_key, second.risk_key)
        self.assertNotEqual(first.risk_instance_id, second.risk_instance_id)
        self.assertNotEqual(first.source_revision, second.source_revision)
        self.assertEqual("rux_03_002_listing_20250619", second.source_batch_id)

    def test_bsa_over_20_generates_stop_review_prompt_from_real_rows(self):
        risks = self._service().evaluate_subject_risks("proj_rux_03_002", "S03040")
        bsa_risk = next(risk for risk in risks if risk.rule_id == "RUX-BSA-TOTAL-GT20-STOP-REVIEW")

        self.assertIn("BSA", bsa_risk.risk_type)
        self.assertTrue(any("BSA--受累体表面积（BSA）" in ref and "row:2185" in ref for ref in bsa_risk.evidence_span_ids))
        self.assertTrue(any("docx:paragraph:748" in ref or "docx:paragraph:883" in ref for ref in bsa_risk.evidence_span_ids))
        self.assertIn("医学确认", bsa_risk.recommended_action)

    def test_subject_monitoring_links_lab_ae_and_dose_adjustment_chain(self):
        profile = self._service().subject_monitoring("proj_rux_03_002", "S01003")

        self.assertEqual("proj_rux_03_002", profile.project_id)
        self.assertEqual("S01003", profile.subject_id)
        timeline_locators = {event.source_locator for event in profile.timeline}
        self.assertTrue(any("LBHEMA--实验室检查-血常规" in locator and "row:231" in locator for locator in timeline_locators))
        self.assertTrue(any("AE--不良事件" in locator and "row:10" in locator for locator in timeline_locators))
        self.assertTrue(any("ECB--研究药物给药-医嘱用药" in locator and "row:3" in locator for locator in timeline_locators))
        ecb_events = [event for event in profile.timeline if event.source_domain == "ECB"]
        self.assertTrue(any("暂停用药" in event.title for event in ecb_events))
        self.assertTrue(any("重新用药" in event.title for event in ecb_events))
        self.assertTrue(all(event.event_type.value == "dose_adjustment" for event in ecb_events))
        self.assertFalse(any(event.source_domain == "CM" and event.event_type.value == "dose_adjustment" for event in profile.timeline))

        safety_metric_keys = {metric.metric_key for metric in profile.safety_trends}
        self.assertIn("anc", safety_metric_keys)
        anc_points = [point for metric in profile.safety_trends if metric.metric_key == "anc" for point in metric.points]
        self.assertTrue(any(point.value == 1.24 and "row:231" in point.source_locator for point in anc_points))

    def test_subject_monitoring_keeps_concomitant_medication_separate_from_study_drug_changes(self):
        profile = self._service().subject_monitoring("proj_rux_03_002", "S01017")

        cm_events = [event for event in profile.timeline if event.source_domain == "CM"]
        self.assertTrue(cm_events)
        self.assertTrue(all(event.event_type.value == "concomitant_medication" for event in cm_events))
        self.assertTrue(any("CM--既往及合并用药治疗" in event.source_locator and "row:283" in event.source_locator for event in cm_events))
        self.assertTrue(any("盐酸左西替利嗪片" in event.title for event in cm_events))
        self.assertTrue(any("非试验用药" in event.detail for event in cm_events))
        self.assertFalse(any(event.source_domain == "ECB" for event in cm_events))

        study_drug_events = [event for event in profile.timeline if event.source_domain == "ECB"]
        self.assertTrue(study_drug_events)
        self.assertTrue(all(event.event_type.value == "dose_adjustment" for event in study_drug_events))
        self.assertFalse(any("CM--既往及合并用药治疗" in event.source_locator for event in study_drug_events))

    def test_patient_profile_exposes_real_rux_efficacy_and_safety_trends(self):
        profile = self._service().subject_monitoring("proj_rux_03_002", "S01003")

        efficacy = {metric.metric_key: metric for metric in profile.efficacy_trends}
        for key in ["bsa_total", "iga", "easi_total", "scorad_total"]:
            self.assertIn(key, efficacy)
            self.assertGreaterEqual(len(efficacy[key].points), 4)
            self.assertTrue(all(point.source_locator for point in efficacy[key].points))

        self.assertTrue(any(point.visit_code == "D1" and point.value == 18.0 and "row:77" in point.source_locator for point in efficacy["bsa_total"].points))
        self.assertTrue(any(point.visit_code == "D29" and point.value == 0.0 and "row:22" in point.source_locator for point in efficacy["iga"].points))
        self.assertTrue(any(point.visit_code == "D1" and point.value == 12.95 and "row:45" in point.source_locator for point in efficacy["easi_total"].points))
        self.assertTrue(any(point.visit_code == "D57" and point.value == 22.5 and "row:12" in point.source_locator for point in efficacy["scorad_total"].points))

        safety = {metric.metric_key: metric for metric in profile.safety_trends}
        for key in ["anc", "alt", "ast"]:
            self.assertIn(key, safety)
            self.assertGreaterEqual(len(safety[key].points), 8)
            self.assertTrue(all(point.source_locator for point in safety[key].points))
        self.assertTrue(any(point.visit_code == "D15" and point.value == 48.0 and "row:244" in point.source_locator and point.risk_flag for point in safety["alt"].points))
        self.assertTrue(any(point.visit_code == "D15" and point.value == 33.0 and "row:245" in point.source_locator for point in safety["ast"].points))

    def test_subject_timeline_includes_real_lab_and_efficacy_risk_events_for_anchor_subjects(self):
        s01017 = self._service().subject_monitoring("proj_rux_03_002", "S01017")
        s01017_locators = {event.source_locator for event in s01017.timeline}
        self.assertTrue(any("LBCHEM--实验室检查-血生化" in locator and "row:1849" in locator for locator in s01017_locators))
        self.assertTrue(any("LBCHEM--实验室检查-血生化" in locator and "row:1863" in locator for locator in s01017_locators))
        self.assertTrue(any(event.source_domain == "LBCHEM" and "ALT" in event.title for event in s01017.timeline))

        s03040 = self._service().subject_monitoring("proj_rux_03_002", "S03040")
        self.assertTrue(any("BSA--受累体表面积（BSA）" in event.source_locator and "row:2185" in event.source_locator for event in s03040.timeline))
        self.assertTrue(any(event.source_domain == "BSA" and event.event_type.value == "efficacy_score" and "BSA" in event.title for event in s03040.timeline))

    def test_subject_monitoring_endpoint_dispatches_rux_project_to_real_service(self):
        client = self._client_with_principal()
        response = client.get("/api/projects/proj_rux_03_002/subjects/S01003/monitoring")

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("proj_rux_03_002", payload["project_id"])
        self.assertEqual("S01003", payload["subject_id"])
        self.assertEqual("待解盲", payload["subject"]["treatment_arm"])
        self.assertNotIn("受试者报表映射", response.text)
        locators = [event["source_locator"] for event in payload["timeline"]]
        self.assertTrue(any("LBHEMA--实验室检查-血常规" in locator and "row:231" in locator for locator in locators))
        self.assertTrue(any("ECB--研究药物给药-医嘱用药" in locator and "row:3" in locator for locator in locators))
        self.assertNotIn("/Users/", response.text)

    def test_subject_monitoring_endpoint_exposes_cm_without_mixing_study_drug_changes(self):
        client = self._client_with_principal()
        response = client.get("/api/projects/proj_rux_03_002/subjects/S01017/monitoring")

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        cm_events = [event for event in payload["timeline"] if event["source_domain"] == "CM"]
        self.assertTrue(cm_events)
        self.assertTrue(all(event["event_type"] == "concomitant_medication" for event in cm_events))
        self.assertTrue(any("CM--既往及合并用药治疗" in event["source_locator"] and "row:283" in event["source_locator"] for event in cm_events))
        self.assertTrue(any("盐酸左西替利嗪片" in event["title"] for event in cm_events))
        self.assertFalse(any("暂停用药" in event["title"] or "重新用药" in event["title"] for event in cm_events))

        study_drug_events = [event for event in payload["timeline"] if event["source_domain"] == "ECB"]
        self.assertTrue(study_drug_events)
        self.assertTrue(all(event["event_type"] == "dose_adjustment" for event in study_drug_events))
        self.assertNotIn("/Users/", response.text)

    def test_rux_dashboard_returns_real_project_metadata_without_mgk10_fallback(self):
        client = self._client_with_current_rux_snapshot()
        response = client.get("/api/projects/proj_rux_03_002/dashboard")
        payload = main_module._rux_dashboard_summary().model_dump(mode="json")

        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            "monitoring_read_action_unconfigured",
            response.json()["detail"]["code"],
        )
        self.assertEqual("proj_rux_03_002", payload["project"]["project_id"])
        self.assertEqual("RUX-03-002", payload["project"]["project_code"])
        self.assertEqual("特应性皮炎", payload["project"]["indication"])
        self.assertEqual("V1.3", payload["project"]["protocol_version"])
        self.assertNotIn("MG-K10", json.dumps(payload, ensure_ascii=False))

        latest_batch = payload["latest_batch"]
        self.assertEqual("rux_03_002_listing_20250612", latest_batch["batch_id"])
        self.assertEqual("2025-06-12", latest_batch["extract_date"])
        modules = {item["module"]: item for item in payload["modules"]}
        self.assertIn("medical_monitoring", modules)
        self.assertEqual("医学监查", modules["medical_monitoring"]["label"])
        self.assertGreaterEqual(modules["medical_monitoring"]["open_risk_count"], 3)

    def test_rux_monitoring_subject_catalog_uses_real_subj_listing_not_demo_pool(self):
        client = self._client_with_principal()
        response = client.get("/api/projects/proj_rux_03_002/monitoring/subjects")

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("proj_rux_03_002", payload["project_id"])
        self.assertEqual(241, payload["subject_count"])
        subject_ids = {item["id"] for item in payload["subjects"]}
        self.assertIn("S01003", subject_ids)
        self.assertIn("S01017", subject_ids)
        self.assertIn("S03040", subject_ids)
        self.assertNotIn("10008", subject_ids)
        self.assertNotIn("06021", subject_ids)
        self.assertNotIn("/Users/", response.text)

        s01003 = next(item for item in payload["subjects"] if item["id"] == "S01003")
        self.assertEqual("01", s01003["site"])
        self.assertIn("中心 01", s01003["profile"])
        self.assertIn("source_locator", s01003)
        self.assertIn("SUBJ--受试者页", s01003["source_locator"])

    def test_workbench_inbox_projects_verified_rux_monitoring_risks(self):
        client = self._client_with_current_rux_snapshot()
        response = client.get("/api/projects/proj_rux_03_002/workbench-inbox?limit=20")

        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            "monitoring_read_action_unconfigured",
            response.json()["detail"]["code"],
        )
        payload = main_module.workbench_inbox_service.inbox(
            "proj_rux_03_002", actor="medical_manager", limit=20
        ).model_dump(mode="json")
        self.assertEqual("proj_rux_03_002", payload["project_id"])
        self.assertGreaterEqual(payload["unread_count"], 1)
        self.assertGreaterEqual(payload["total_open_count"], 3)
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("/Users/", "content_hash", "preview_hash", "storage_key", "server_path", "source_record_id"):
            self.assertNotIn(forbidden, serialized)

        items = [
            item for item in payload["items"]
            if item["module"] == "medical_monitoring" and item["item_type"] == "risk"
        ]
        self.assertTrue(items)
        subjects = {item.get("target_id") for item in items}
        self.assertIn("S01017", subjects)
        self.assertIn("S01003", subjects)
        self.assertIn("S03040", subjects)
        self.assertTrue(all(item["module_label"] == "医学监查" for item in items))
        self.assertTrue(all(item["target_page"] == "monitoring" for item in items))
        self.assertTrue(all(item["status"] == "待医学复核" for item in items))
        self.assertTrue(all(item["action_label"] == "标记医学复核" for item in items))
        self.assertTrue(all("RUX原始listing、方案条款和当前项目规则版本" in item["boundary_note"] for item in items))
        self.assertTrue(all("每条结论仍需医学复核" in item["boundary_note"] for item in items))

        for item in items:
            source_refs = item.get("source_refs", [])
            self.assertTrue(any(ref["source_type"] == "listing_data_row" and ref["locator"].startswith("listing:") for ref in source_refs))
            self.assertTrue(any(ref["source_type"] == "protocol_rule" and ref["locator"].startswith("docx:") for ref in source_refs))
