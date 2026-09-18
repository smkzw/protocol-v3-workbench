from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
import io
from pathlib import Path

from fastapi.testclient import TestClient
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import ApprovalState, RiskSeverity  # noqa: E402
from packages.contracts.workbench_contracts.models import SubjectTimelineEvent, SubjectTimelineEventType, SubjectTrendPoint  # noqa: E402
from services.api.app.demo_repository import DemoRepository  # noqa: E402
import services.api.app.main as main_module  # noqa: E402
from services.api.app.main import app  # noqa: E402
from services.api.app.monitoring_identity_authorization import MonitoringRole  # noqa: E402
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal  # noqa: E402


class WorkbenchContractTests(unittest.TestCase):
    class _PrincipalMiddleware:
        def __init__(self, application, principal):
            self.application = application
            self.principal = principal

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope.setdefault("state", {})["monitoring_principal"] = self.principal
            await self.application(scope, receive, send)

    @classmethod
    def setUpClass(cls):
        data_path = PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
        cls.repo = DemoRepository(data_path)
        principal = MonitoringAuthenticatedPrincipal(
            principal_id="contracts-monitoring-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_mgk10_sar_demo",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="contracts-monitoring-test-session",
            directory_revision="contracts-monitoring-test-v1",
            verification_ref_sha256="1" * 64,
        )
        cls.client = TestClient(cls._PrincipalMiddleware(app, principal))

    def test_dashboard_has_priority_modules(self):
        dashboard = self.repo.dashboard("proj_mgk10_sar_demo")
        modules = {item.module for item in dashboard.modules}
        self.assertEqual({"dashboard", "evidence_design", "eligibility_review", "medical_monitoring", "data_analysis_tfl", "medical_writing", "safety_pv", "approvals"}, modules)
        self.assertGreaterEqual(len(dashboard.recent_risks), 3)

    def test_module_catalog_only_builds_medical_related_subsystems(self):
        catalog = self.repo.module_catalog("proj_mgk10_sar_demo")
        modules = {item.module for item in catalog.modules}

        self.assertEqual({"dashboard", "evidence_design", "eligibility_review", "medical_monitoring", "data_analysis_tfl", "medical_writing", "safety_pv", "approvals"}, modules)
        self.assertFalse({"stage1", "stage1_interface", "stage4", "stage4_interface", "stage5", "stage5_interface"} & modules)
        self.assertFalse({"project_startup", "site_operations", "edc_build", "recruitment_operations"} & modules)

        label_by_module = {item.module: item.label for item in catalog.modules}
        self.assertEqual("证据调研与方案设计", label_by_module["evidence_design"])
        self.assertEqual("数据分析与TFL", label_by_module["data_analysis_tfl"])
        self.assertEqual("安全信号与PV协同", label_by_module["safety_pv"])
        forbidden_text_fragments = (
            "阶段",
            "第",
            "环节",
            "3/6/8",
            "2/7/9",
            "项目启动",
            "中心启动",
            "EDC构建",
            "数据采集系统",
            "临床运营",
            "受试者招募",
        )
        for label in label_by_module.values():
            self.assertNotIn("阶段", label)
            self.assertNotIn("第", label)
        for item in catalog.modules:
            self.assertIsNone(item.lifecycle_step)
            visible_text = f"{item.label} {item.note}"
            self.assertFalse(any(fragment in visible_text for fragment in forbidden_text_fragments), visible_text)

    def test_module_catalog_endpoint_returns_same_medical_scope(self):
        response = self.client.get("/api/projects/proj_mgk10_sar_demo/module-catalog")
        self.assertEqual(200, response.status_code)
        modules = {item["module"] for item in response.json()["modules"]}

        self.assertIn("evidence_design", modules)
        self.assertIn("safety_pv", modules)
        self.assertNotIn("stage1_interface", modules)
        self.assertNotIn("stage4_interface", modules)
        self.assertNotIn("stage5_interface", modules)
        self.assertFalse({"project_startup", "site_operations", "edc_build", "recruitment_operations"} & modules)

        serialized = response.text
        forbidden_visible_fragments = (
            "第1环节",
            "第一环节",
            "第4环节",
            "第四环节",
            "第5环节",
            "第五环节",
            "阶段1",
            "阶段4",
            "阶段5",
            "Stage 1",
            "Stage 4",
            "Stage 5",
            "项目启动",
            "中心启动",
            "EDC构建",
            "数据采集系统",
            "临床运营",
            "受试者招募",
        )
        self.assertFalse(any(fragment in serialized for fragment in forbidden_visible_fragments), serialized)
        cross_project = self.client.get("/api/projects/proj_rux_03_002/module-catalog")
        self.assertEqual(403, cross_project.status_code, cross_project.text)

    def test_ai_gateway_status_endpoint_does_not_depend_on_codex(self):
        response = self.client.get("/api/ai-gateway/status")
        self.assertEqual(200, response.status_code)
        status = response.json()
        self.assertFalse(status["codex_runtime_dependency"])
        self.assertIn("semantic_ai_tasks_enabled", status)
        self.assertIn("WORKBENCH_AI_MODEL", status["required_env"])

    def test_reference_translation_status_separates_flash_support_from_hy_body(self):
        response = self.client.get(
            "/api/medical-writing/reference-translation/ai-status"
        )
        self.assertEqual(200, response.status_code)
        status = response.json()
        self.assertEqual("deepseek", status["provider"])
        self.assertEqual("deepseek-v4-flash", status["model"])
        self.assertEqual("openai_compatible", status["transport"])
        self.assertEqual(
            "regulatory_protocol_translation_zh",
            status["task_type"],
        )
        self.assertEqual(
            "medical_writing_reference_translation",
            status["runtime_scope"],
        )
        self.assertEqual("dedicated", status["audit_store"])
        self.assertEqual(
            [
                "toc_and_chapter_planning",
                "post_hy_mt2_integration_qc",
                "corpus_selection_support",
            ],
            status["deepseek_role"],
        )
        self.assertEqual(
            "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            status["body_translation_model"],
        )
        self.assertEqual("local_omlx", status["body_translation_provider"])
        self.assertTrue(status["execution_chain_wired"])
        self.assertIsInstance(status["body_translation_runnable"], bool)
        self.assertEqual(
            status["translation_body"]["current_runnable"],
            status["body_translation_runnable"],
        )
        # The test package isolates runtime state and does not provide a
        # cloud credential. The endpoint must reflect actual role readiness,
        # rather than claiming the default support model is runnable.
        self.assertEqual(
            status["currently_runnable"],
            status["body_translation_runnable"]
            and status["support_runnable"]
            and status["ocr"]["current_runnable"],
        )
        self.assertEqual(
            {"ocr": 8, "translation": 8, "total": 16},
            status["omlx_workload_gate"]["limits"],
        )
        self.assertFalse(status["deepseek_body_translation_allowed"])
        self.assertFalse(status["codex_runtime_dependency"])
        self.assertIsInstance(status["api_key_configured"], bool)
        self.assertNotIn("api_key_value", status)
        self.assertNotIn("/Users/", response.text)

    def test_health_endpoint_does_not_expose_local_paths(self):
        response = self.client.get("/api/health")
        self.assertEqual(200, response.status_code)
        serialized = response.text
        self.assertIn("data_exists", response.json())
        self.assertNotIn("data_path", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_dashboard_module_labels_are_business_names(self):
        dashboard = self.repo.dashboard("proj_mgk10_sar_demo")
        labels = {item.label for item in dashboard.modules}
        self.assertEqual(
            {"项目总看板", "证据调研与方案设计", "入排审核", "医学监查", "数据分析与TFL", "医学写作", "安全信号与PV协同", "审批中心"},
            labels,
        )
        forbidden_fragments = ("Stage", "stage", "阶段", "第2环节", "第3环节", "第6环节", "第7环节", "第8环节", "第9环节")
        for label in labels:
            self.assertFalse(any(fragment in label for fragment in forbidden_fragments), label)

    def test_medical_writing_protocol_starts_without_preset_ai_revision_thread(self):
        protocol = self.repo.protocol("proj_mgk10_sar_demo")
        self.assertEqual("clinical_study_protocol", protocol.document_type)
        section_ids = {section.section_id for section in protocol.sections}
        self.assertIn("sec_objectives_endpoints", section_ids)
        threads = self.repo.revision_threads("proj_mgk10_sar_demo")
        self.assertEqual([], threads)

    def test_medical_monitoring_demo_starts_from_edc_listing_batches(self):
        batches = self.repo.batches("proj_mgk10_sar_demo")
        self.assertEqual(3, len(batches))
        self.assertEqual("batch_002", batches[2].previous_batch_id)
        risks = self.repo.risks("proj_mgk10_sar_demo")
        medical_monitoring = [risk for risk in risks if risk.module == "medical_monitoring"]
        self.assertTrue(medical_monitoring)
        self.assertTrue(any(risk.severity == RiskSeverity.HIGH for risk in medical_monitoring))

    def test_medical_monitoring_subject_monitoring_has_two_subjects_and_required_domains(self):
        profiles = self.repo.subject_monitoring_profiles("proj_mgk10_sar_demo")
        self.assertGreaterEqual(len(profiles), 2)
        self.assertEqual({"06021", "10008"}, {profile.subject_id for profile in profiles})

        forbidden_fragments = ("Stage", "stage", "阶段", "第6环节")
        for profile in profiles:
            self.assertEqual("medical_monitoring", profile.module)
            self.assertEqual("医学监查", profile.module_label)
            self.assertFalse(any(fragment in profile.module_label for fragment in forbidden_fragments))
            self.assertTrue(profile.timeline)
            self.assertTrue(profile.efficacy_trends)
            self.assertTrue(profile.safety_trends)
            self.assertTrue(profile.risk_prompts)

        event_types = {event.event_type for profile in profiles for event in profile.timeline}
        required = {
            SubjectTimelineEventType.ADVERSE_EVENT,
            SubjectTimelineEventType.MEDICAL_HISTORY,
            SubjectTimelineEventType.CONCOMITANT_MEDICATION,
            SubjectTimelineEventType.LAB,
            SubjectTimelineEventType.EFFICACY_SCORE,
            SubjectTimelineEventType.VISIT,
            SubjectTimelineEventType.PROTOCOL_DEVIATION,
            SubjectTimelineEventType.QUERY,
        }
        self.assertTrue(required.issubset(event_types))

    def test_subject_monitoring_events_and_trends_expose_source_locators(self):
        self.assertIn("source_locator", SubjectTimelineEvent.model_fields)
        self.assertIn("source_locator", SubjectTrendPoint.model_fields)

        profile = self.repo.subject_monitoring("proj_mgk10_sar_demo", "10008")
        self.assertTrue(profile.timeline)
        self.assertTrue(profile.efficacy_trends or profile.safety_trends)
        for event in profile.timeline:
            self.assertTrue(event.source_domain)
            self.assertTrue(event.source_record_id)
            self.assertTrue(event.source_locator)
        for metric in profile.efficacy_trends + profile.safety_trends:
            for point in metric.points:
                self.assertTrue(point.source_domain)
                self.assertTrue(point.source_record_id)
                self.assertTrue(point.source_locator)

    def test_medical_monitoring_subject_monitoring_trends_and_timepoint_prompts(self):
        profile = self.repo.subject_monitoring("proj_mgk10_sar_demo", "06021")
        efficacy_metric_keys = {metric.metric_key for metric in profile.efficacy_trends}
        safety_metric_keys = {metric.metric_key for metric in profile.safety_trends}
        self.assertIn("rtnss_total", efficacy_metric_keys)
        self.assertIn("rtoss_total", efficacy_metric_keys)
        self.assertIn("eosinophil_abs", safety_metric_keys)

        all_points = [point for metric in profile.efficacy_trends + profile.safety_trends for point in metric.points]
        self.assertTrue(any(point.visit_code == "W2" and point.risk_flag for point in all_points))
        self.assertTrue(
            any(
                prompt.visit_code == "W2"
                and prompt.query_id == "QRY-06021-QS-002"
                and {"QS", "PD", "QUERY"}.issubset(set(prompt.trigger_domains))
                for prompt in profile.risk_prompts
            )
        )

    def test_subject_monitoring_endpoint_returns_project_subject_drilldown(self):
        response = self.client.get("/api/projects/proj_mgk10_sar_demo/subjects/10008/monitoring")
        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("proj_mgk10_sar_demo", payload["project_id"])
        self.assertEqual("10008", payload["subject_id"])
        self.assertEqual("medical_monitoring", payload["module"])
        self.assertEqual("医学监查", payload["module_label"])
        self.assertTrue(payload["timeline"])
        self.assertTrue(payload["efficacy_trends"])
        self.assertTrue(payload["safety_trends"])
        self.assertTrue(payload["risk_prompts"])

    def test_subject_monitoring_endpoint_returns_404_for_unknown_subject(self):
        response = self.client.get("/api/projects/proj_mgk10_sar_demo/subjects/not-a-subject/monitoring")
        self.assertEqual(404, response.status_code)

    def test_eligibility_endpoint_reads_original_enrollment_project(self):
        response = self.client.get(
            "/api/projects/proj_mgk10_sar_demo/eligibility?subject_id=31014&phase=baseline_randomization"
        )
        self.assertEqual(200, response.status_code)
        payload = response.json()

        self.assertEqual("enrollment-review-app", payload["source_system"])
        self.assertEqual("MG-K10-SAR-III", payload["source_project_code"])
        self.assertEqual("MG-K10-SAR-001", payload["protocol_id"])
        self.assertEqual("V2.1", payload["protocol_version"])
        self.assertEqual("baseline_randomization", payload["active_phase_id"])
        self.assertEqual(10, payload["project_stats"]["total_subjects"])
        self.assertEqual(23, payload["project_stats"]["criteria_rule_count"])
        self.assertIn("IN-05", payload["criteria_rule_ids"])
        self.assertIn("EX-07", payload["criteria_rule_ids"])
        self.assertEqual({"screening_run_in", "baseline_randomization"}, {phase["phase_id"] for phase in payload["review_phases"]})
        self.assertEqual(10, len(payload["subject_rows"]))
        self.assertGreaterEqual(payload["audit_summary"]["event_count"], 1)

        selected = payload["selected_candidate"]
        self.assertEqual("31014", selected["subject_id"])
        self.assertEqual("baseline_randomization", selected["active_phase_id"])
        self.assertEqual(23, len(selected["rule_reviews"]))
        rule_map = {rule["rule_id"]: rule for rule in selected["rule_reviews"]}
        self.assertEqual("基线嗜酸性粒细胞计数", rule_map["IN-05"]["rule_label"])
        self.assertEqual("insufficient", rule_map["IN-05"]["verdict"])
        self.assertEqual("疾病史", rule_map["EX-07"]["rule_label"])
        self.assertEqual("pass", rule_map["EX-07"]["verdict"])
        self.assertTrue(selected["missing_information"])
        self.assertTrue(payload["available_actions"])

    def test_eligibility_endpoint_returns_404_for_unknown_project(self):
        response = self.client.get("/api/projects/unknown-project/eligibility")
        self.assertEqual(404, response.status_code)

    def test_ai_formal_content_uses_approval_gate(self):
        approvals = self.repo.approvals("proj_mgk10_sar_demo")
        states = {approval.state for approval in approvals}
        self.assertIn(ApprovalState.IN_MEDICAL_REVIEW, states)
        self.assertIn(ApprovalState.AI_DRAFT, states)

    def test_monitoring_intake_endpoint_detects_mapping_diff_and_risks(self):
        payload = {
            "batch_label": "EDC listing Batch 004",
            "extract_date": "2026-07-07",
            "previous_batch_id": "batch_003",
            "uploaded_by": "medical_manager",
            "sheets": [
                {
                    "sheet_name": "CM",
                    "rows": [
                        {
                            "SUBJID": "10008",
                            "SITEID": "10",
                            "VISIT": "SCR",
                            "RANDDTC": "2026-07-06",
                            "CMTRT": "氯雷他定",
                            "CMSTDTC": "2026-06-30",
                            "CMENDTC": "2026-07-05",
                            "CMINDC": "鼻痒、喷嚏",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                },
                {
                    "sheet_name": "AE",
                    "rows": [
                        {
                            "SUBJID": "10008",
                            "SITEID": "10",
                            "VISIT": "W1",
                            "AETERM": "头痛",
                            "AESTDTC": "2026-07-13",
                            "AESI_FLAG": "N",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                },
            ],
        }
        response = self.client.post("/api/projects/proj_mgk10_sar_demo/monitoring/intake", json=payload)
        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertNotIn("第4批", result["batch"]["batch_label"])
        self.assertEqual("requires_confirmation", result["mapping_status"])
        self.assertTrue(any(item["source_field"] == "AESI_FLAG" for item in result["field_mappings"]))
        self.assertRegex(result["batch"]["batch_id"], r"^batch_00[4-9]$")
        self.assertEqual(2, result["diff_summary"]["added_row_count"])
        self.assertGreaterEqual(result["rule_run"]["generated_risk_count"], 1)
        self.assertTrue(any(risk["risk_type"] == "禁用药/洗脱违规" for risk in result["generated_risks"]))

        risks_response = self.client.get("/api/projects/proj_mgk10_sar_demo/risks")
        self.assertEqual(200, risks_response.status_code)
        risk_ids = {risk["risk_id"] for risk in risks_response.json()}
        self.assertTrue(set(risk["risk_id"] for risk in result["generated_risks"]).issubset(risk_ids))

        batches_response = self.client.get("/api/projects/proj_mgk10_sar_demo/data-batches")
        self.assertEqual(200, batches_response.status_code)
        self.assertTrue(any(batch["batch_id"] == result["batch"]["batch_id"] for batch in batches_response.json()))

        dashboard_response = self.client.get("/api/projects/proj_mgk10_sar_demo/dashboard")
        self.assertEqual(403, dashboard_response.status_code)
        self.assertEqual(
            "monitoring_read_action_unconfigured",
            dashboard_response.json()["detail"]["code"],
        )
        dashboard = main_module.repo.dashboard("proj_mgk10_sar_demo").model_dump(mode="json")
        self.assertEqual(result["batch"]["batch_id"], dashboard["latest_batch"]["batch_id"])
        medical_monitoring = [module for module in dashboard["modules"] if module["module"] == "medical_monitoring"][0]
        self.assertGreaterEqual(medical_monitoring["open_risk_count"], len(result["generated_risks"]))

        followup = self.client.get(
            f"/api/projects/proj_mgk10_sar_demo/monitoring/intake/{result['session_id']}"
        )
        self.assertEqual(200, followup.status_code)
        self.assertEqual(result["session_id"], followup.json()["session_id"])

    def test_monitoring_intake_confirmed_mapping_runs_without_mapping_block(self):
        payload = {
            "batch_label": "EDC listing Batch 004",
            "extract_date": "2026-07-07",
            "previous_batch_id": "batch_003",
            "uploaded_by": "medical_manager",
            "mapping_confirmations": {"AESI_FLAG": "safety_interest_flag"},
            "sheets": [
                {
                    "sheet_name": "AE",
                    "rows": [
                        {
                            "SUBJID": "06021",
                            "SITEID": "06",
                            "VISIT": "W2",
                            "AETERM": "头痛",
                            "AESTDTC": "2026-07-19",
                            "AESI_FLAG": "N",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                },
                {
                    "sheet_name": "MH",
                    "rows": [
                        {
                            "SUBJID": "06021",
                            "SITEID": "06",
                            "VISIT": "SCR",
                            "MHTERM": "过敏性结膜炎史",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                },
            ],
        }
        response = self.client.post("/api/projects/proj_mgk10_sar_demo/monitoring/intake", json=payload)
        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("confirmed", result["mapping_status"])
        self.assertFalse(result["rule_run"]["blocked_by_mapping"])
        self.assertTrue(any(risk["risk_type"] == "AE/MH漏报" for risk in result["generated_risks"]))

    def test_monitoring_washout_rule_uses_randomization_date_not_hardcoded_cutoff(self):
        safe_payload = {
            "batch_label": "EDC listing 洗脱验证",
            "extract_date": "2026-07-07",
            "previous_batch_id": "batch_003",
            "uploaded_by": "medical_manager",
            "sheets": [
                {
                    "sheet_name": "CM",
                    "rows": [
                        {
                            "SUBJID": "SAFE01",
                            "SITEID": "10",
                            "VISIT": "SCR",
                            "RANDDTC": "2026-07-06",
                            "CMTRT": "氯雷他定",
                            "CMENDTC": "2026-07-01",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                }
            ],
        }
        safe_response = self.client.post("/api/projects/proj_mgk10_sar_demo/monitoring/intake", json=safe_payload)
        self.assertEqual(200, safe_response.status_code, safe_response.text)
        self.assertFalse(
            any(risk["risk_type"] == "禁用药/洗脱违规" for risk in safe_response.json()["generated_risks"])
        )

        risk_payload = safe_payload | {
            "sheets": [
                {
                    "sheet_name": "CM",
                    "rows": [
                        {
                            "SUBJID": "RISK01",
                            "SITEID": "10",
                            "VISIT": "SCR",
                            "RANDDTC": "2026-07-06",
                            "CMTRT": "氯雷他定",
                            "CMENDTC": "2026-07-05",
                            "CHANGE_FLAG": "new",
                        }
                    ],
                }
            ],
        }
        risk_response = self.client.post("/api/projects/proj_mgk10_sar_demo/monitoring/intake", json=risk_payload)
        self.assertEqual(200, risk_response.status_code, risk_response.text)
        self.assertTrue(any(risk["risk_type"] == "禁用药/洗脱违规" for risk in risk_response.json()["generated_risks"]))

    def test_monitoring_intake_file_endpoint_parses_raw_xlsx(self):
        workbook = openpyxl.Workbook()
        cm = workbook.active
        cm.title = "CM"
        cm.append(["STUDYID", "SUBJID", "SITEID", "VISIT", "RANDDTC", "CMTRT", "CMENDTC", "CMINDC", "CHANGE_FLAG"])
        cm.append(["MG-K10-SAR-III", "10008", "10", "SCR", "2026-07-06", "氯雷他定", "2026-07-05", "鼻痒、喷嚏", "new"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()

        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/monitoring/intake/file",
            params={
                "filename": "batch_004_raw.xlsx",
                "extract_date": "2026-07-07",
                "previous_batch_id": "batch_003",
                "batch_label": "EDC listing Batch 004",
            },
            content=buffer.getvalue(),
            headers={"Content-Type": "application/octet-stream"},
        )

        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual("rules_run", result["batch"]["status"])
        self.assertEqual(1, result["batch"]["row_count"])
        self.assertEqual({"CM": 1}, result["diff_summary"]["sheet_row_counts"])
        self.assertTrue(any(risk["risk_type"] == "禁用药/洗脱违规" for risk in result["generated_risks"]))
        self.assertEqual("matched", result["content_validation"]["content_status"])
        self.assertEqual("allowed", result["content_validation"]["use_status"])


if __name__ == "__main__":
    unittest.main()
