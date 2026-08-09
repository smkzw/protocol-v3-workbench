from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import services.api.app.main as main_module  # noqa: E402
from services.api.app.main import app  # noqa: E402
from services.api.app.medical_monitoring_summary import MedicalMonitoringRunService  # noqa: E402
from services.api.app.medical_risk_repository import MedicalRiskRepository  # noqa: E402
from services.api.app.monitoring_identity_authorization import MonitoringRole  # noqa: E402
from services.api.app.monitoring_runtime_principal import (  # noqa: E402
    MonitoringAuthenticatedPrincipal,
)

try:
    from services.api.app.my009_monitoring_service import My009MonitoringService
except Exception as exc:  # pragma: no cover - exercised by the initial TDD red run.
    My009MonitoringService = None
    MY009_SERVICE_IMPORT_ERROR = exc
else:
    MY009_SERVICE_IMPORT_ERROR = None


PROJECT_ID = "proj_my009_uc"
LISTING_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/S1安全性评价-202604/"
    "MY009-UC-2-01-MM Listing_20260408(已自动还原).xlsx"
)
PROTOCOL_PATH = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
ANCHOR_SUBJECTS = {"S01003", "S01008", "S01009", "S08001", "S05003"}
DEMO_SUBJECTS = {"10008", "06021", "10021", "10045", "10031"}
PUBLIC_LISTING_LABEL = "MY009-UC-MM-Listing"


@unittest.skipUnless(LISTING_PATH.exists() and PROTOCOL_PATH.exists(), "MY009 raw monitoring sources unavailable")
class My009MonitoringServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if My009MonitoringService is None:
            cls.service = None
            return
        cls.service = My009MonitoringService(
            listing_path=LISTING_PATH,
            protocol_path=PROTOCOL_PATH,
            listing_label=PUBLIC_LISTING_LABEL,
        )
        cls._isolated_risk_repository = None
        cls._isolated_risk_runtime = None

    def _service(self):
        if self.service is None:
            self.fail(f"My009MonitoringService must exist as an additive real-data adapter: {MY009_SERVICE_IMPORT_ERROR}")
        return self.service

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="my009-monitoring-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_my009_uc", "proj_rux_03_002", "proj_d001"),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="my009-monitoring-test-session",
            directory_revision="my009-monitoring-test-v1",
            verification_ref_sha256="c" * 64,
        )

    @classmethod
    def _my009_risk_repository(cls) -> MedicalRiskRepository:
        if cls._isolated_risk_repository is not None:
            return cls._isolated_risk_repository

        runtime = tempfile.TemporaryDirectory()
        cls.addClassCleanup(runtime.cleanup)
        repository = MedicalRiskRepository(Path(runtime.name) / "medical_risks.sqlite3")
        run_service = MedicalMonitoringRunService(
            risk_repository=repository,
            project_source_manifest_service=main_module.project_source_manifest_service,
            monitoring_registry=main_module.monitoring_project_registry,
        )
        result = run_service.run(PROJECT_ID)
        if result["status"] != "snapshot_generated" or result["risk_count"] <= 0:
            raise AssertionError(f"isolated MY009 risk snapshot was not generated: {result}")

        cls._isolated_risk_runtime = runtime
        cls._isolated_risk_repository = repository
        return repository

    @contextmanager
    def _isolated_my009_api_client(self):
        repository = self._my009_risk_repository()
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(main_module, "medical_risk_repository", repository)
            )
            stack.enter_context(
                patch.object(
                    main_module.medical_monitoring_summary_service,
                    "risk_repository",
                    repository,
                )
            )
            stack.enter_context(
                patch.object(
                    main_module.workbench_inbox_service,
                    "medical_risk_repository",
                    repository,
                )
            )
            yield TestClient(app)

    def test_protocol_rule_registry_resolves_only_real_my009_anchors(self):
        registry = self._service().protocol_rule_registry()
        rules = [rule for group in registry.values() for rule in group]

        self.assertTrue(rules)
        self.assertTrue(all(rule["rule_id"].startswith("MY009-UC-") for rule in rules))
        self.assertTrue(all(rule["resolved"] for rule in rules))
        self.assertTrue(all(rule["source_text"].strip() for rule in rules))
        locators = {rule["source_locator"] for rule in rules}
        self.assertIn("docx:table:7:row:30", locators)
        self.assertIn("docx:paragraph:1351", locators)
        self.assertIn("docx:paragraph:1499", locators)
        self.assertIn("docx:paragraph:1609", locators)
        serialized = json.dumps(registry, ensure_ascii=False)
        self.assertNotIn("RUX-", serialized)
        self.assertNotIn("BSA", serialized)

    def test_subject_catalog_uses_26_real_subjects_and_canonical_public_locators(self):
        catalog = self._service().subject_catalog(PROJECT_ID)

        self.assertEqual(PROJECT_ID, catalog["project_id"])
        self.assertEqual(26, catalog["subject_count"])
        subject_ids = {item["id"] for item in catalog["subjects"]}
        self.assertTrue(ANCHOR_SUBJECTS.issubset(subject_ids))
        self.assertFalse(DEMO_SUBJECTS.intersection(subject_ids))
        self.assertEqual(8, len({item["site"] for item in catalog["subjects"]}))
        self.assertEqual("01", next(item["site"] for item in catalog["subjects"] if item["id"] == "S01003"))
        self.assertTrue(all(item["source_locator"].startswith(f"listing:{PUBLIC_LISTING_LABEL}:sheet:") for item in catalog["subjects"]))
        serialized = json.dumps(catalog, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("已自动还原", serialized)

    def test_s01003_timeline_is_visit_axis_based_and_keeps_cm_separate_from_study_drug(self):
        profile = self._service().subject_monitoring(PROJECT_ID, "S01003")

        self.assertEqual("待解盲", profile.subject.treatment_arm)
        self.assertEqual("01", profile.subject.site_id)
        self.assertTrue(any(event.event_type.value == "visit" and event.source_domain == "SV" for event in profile.timeline))
        self.assertTrue(any(event.event_type.value == "medical_history" for event in profile.timeline))
        self.assertTrue(any(event.event_type.value == "lab" for event in profile.timeline))
        self.assertTrue(any(event.event_type.value == "efficacy_score" for event in profile.timeline))

        cm_events = [event for event in profile.timeline if event.source_domain in {"CM", "CM1", "HBYY", "JWYY"}]
        study_drug_events = [event for event in profile.timeline if event.source_domain in {"DA", "EX", "EX2", "EX3"}]
        self.assertTrue(cm_events)
        self.assertTrue(study_drug_events)
        self.assertTrue(all(event.event_type.value == "concomitant_medication" for event in cm_events))
        self.assertEqual("non_study_medication", cm_events[0].event_subtype.value)
        self.assertTrue(
            {
                "study_drug_dispensing",
                "study_drug_administration",
                "study_drug_adherence",
            }.issubset({event.event_type.value for event in study_drug_events})
        )
        self.assertFalse(
            any(
                event.event_type.value == "dose_adjustment"
                and event.event_subtype.value == "study_drug_adherence"
                for event in study_drug_events
            )
        )
        self.assertFalse(any(event.source_domain in {"DA", "EX", "EX2", "EX3"} for event in cm_events))
        self.assertFalse(any(event.source_domain in {"CM", "CM1", "HBYY", "JWYY"} for event in study_drug_events))
        self.assertTrue(all(event.source_locator.startswith(f"listing:{PUBLIC_LISTING_LABEL}:sheet:") for event in profile.timeline))
        anemia = next(event for event in profile.timeline if event.title == "贫血")
        self.assertEqual("2016", anemia.event_date)
        self.assertEqual("2016-UK-UK", anemia.raw_event_date)
        self.assertEqual("year", anemia.date_precision.value)
        self.assertEqual("2016-01-01", anemia.earliest_possible_date)
        self.assertEqual("2016-12-31", anemia.latest_possible_date)
        self.assertEqual("partial", anemia.date_parse_status)
        self.assertNotEqual(profile.subject.baseline_visit_date, anemia.event_date)
        self.assertTrue(profile.visit_anchors)

    def test_patient_profile_exposes_real_uc_efficacy_and_safety_trends(self):
        profile = self._service().subject_monitoring(PROJECT_ID, "S01003")

        efficacy = {metric.metric_key: metric for metric in profile.efficacy_trends}
        self.assertIn("partial_mayo", efficacy)
        self.assertGreaterEqual(len(efficacy["partial_mayo"].points), 5)
        self.assertTrue(all(point.source_domain == "QS" for point in efficacy["partial_mayo"].points))

        safety = {metric.metric_key: metric for metric in profile.safety_trends}
        for key in ["alt", "ast", "wbc", "hemoglobin", "platelet"]:
            self.assertIn(key, safety)
            self.assertGreaterEqual(len(safety[key].points), 4)
            self.assertTrue(all(point.source_locator.startswith(f"listing:{PUBLIC_LISTING_LABEL}:sheet:") for point in safety[key].points))
        self.assertTrue(any(point.risk_flag for point in safety["wbc"].points))

    def test_real_listing_and_protocol_generate_bounded_review_risks(self):
        s01003 = self._service().evaluate_subject_risks(PROJECT_ID, "S01003")
        self.assertTrue(any(risk.rule_id == "MY009-UC-IP-ADHERENCE-001" for risk in s01003))
        adherence = next(risk for risk in s01003 if risk.rule_id == "MY009-UC-IP-ADHERENCE-001")
        self.assertEqual(
            "study_treatment_adherence",
            adherence.primary_category,
        )
        self.assertIn("potential_pd", adherence.tags)
        self.assertTrue(any(":sheet:EX2:" in ref or ":sheet:EX3:" in ref for ref in adherence.evidence_span_ids))
        self.assertIn("docx:paragraph:1609", adherence.evidence_span_ids)

        s08001 = self._service().evaluate_subject_risks(PROJECT_ID, "S08001")
        lab_review = next(risk for risk in s08001 if risk.rule_id == "MY009-UC-LAB-CS-REVIEW-001")
        self.assertTrue(any(":sheet:LB2:" in ref for ref in lab_review.evidence_span_ids))
        self.assertIn("docx:paragraph:1351", lab_review.evidence_span_ids)

        for subject_id in ANCHOR_SUBJECTS:
            for risk in self._service().evaluate_subject_risks(PROJECT_ID, subject_id):
                self.assertTrue(risk.rule_id.startswith("MY009-UC-"))
                self.assertEqual(PROJECT_ID, risk.project_id)
                self.assertNotIn("RUX", risk.title)
                self.assertNotIn("已确认", risk.rationale)

    def test_real_my009_risks_use_stable_keys_and_source_bound_instances(self):
        risks = self._service().evaluate_subject_risks(PROJECT_ID, "S01003")
        adherence_risks = [item for item in risks if item.rule_id == "MY009-UC-IP-ADHERENCE-001"]
        self.assertGreaterEqual(len(adherence_risks), 2)
        self.assertTrue(all(item.aggregation_scope == "episode" for item in adherence_risks))
        self.assertTrue(all(item.episode_key for item in adherence_risks))
        self.assertEqual(len(adherence_risks), len({item.episode_key for item in adherence_risks}))
        self.assertEqual(len(adherence_risks), len({item.risk_key for item in adherence_risks}))

        risk = adherence_risks[0]

        self.assertTrue(risk.risk_key.startswith("riskkey_"))
        self.assertTrue(risk.risk_instance_id.startswith("riskinst_"))
        self.assertNotEqual(risk.risk_key, risk.risk_instance_id)
        self.assertEqual("subject", risk.scope_type)
        self.assertEqual("S01003", risk.scope_id)
        self.assertTrue(risk.source_revision.startswith("monsrcv_"))
        self.assertEqual("my009-protocol-v3.0-rules-v1", risk.rule_profile_revision)
        self.assertEqual("my009-monitoring-risk-v0.9", risk.engine_version)
        self.assertEqual("my009-protocol-v3.0-rules-v1", self._service().risk_profile_revision())
        self.assertEqual("my009-monitoring-risk-v0.9", self._service().risk_engine_version())

        lab_risk = next(
            item
            for item in self._service().evaluate_subject_risks(PROJECT_ID, "S08001")
            if item.rule_id == "MY009-UC-LAB-CS-REVIEW-001"
        )
        self.assertEqual("rule_scope", lab_risk.aggregation_scope)
        self.assertEqual("", lab_risk.episode_key)

    def test_my009_timeline_and_profile_points_link_to_the_same_risk_instance(self):
        risks = self._service().evaluate_subject_risks(PROJECT_ID, "S08001")
        risk = next(item for item in risks if item.rule_id == "MY009-UC-LAB-CS-REVIEW-001")
        profile = self._service().subject_monitoring(PROJECT_ID, "S08001")

        linked_events = [event for event in profile.timeline if risk.risk_instance_id in event.related_risk_ids]
        linked_points = [
            point
            for metric in profile.efficacy_trends + profile.safety_trends
            for point in metric.points
            if risk.risk_instance_id in point.related_risk_ids
        ]

        self.assertTrue(any(":sheet:LB2:row:729" in event.source_locator for event in linked_events))
        self.assertTrue(any(":sheet:LB2:row:729" in point.source_locator for point in linked_points))

    def test_batch_context_changes_instance_identity_but_not_stable_risk_key(self):
        first = next(
            item
            for item in self._service().evaluate_subject_risks(PROJECT_ID, "S01003")
            if item.rule_id == "MY009-UC-IP-ADHERENCE-001"
        )
        next_batch_service = My009MonitoringService(
            listing_path=LISTING_PATH,
            protocol_path=PROTOCOL_PATH,
            listing_label=PUBLIC_LISTING_LABEL,
            source_batch_id="my009_uc_listing_20260410",
        )
        second = next(
            item
            for item in next_batch_service.evaluate_subject_risks(PROJECT_ID, "S01003")
            if item.rule_id == "MY009-UC-IP-ADHERENCE-001"
        )

        self.assertEqual(first.risk_key, second.risk_key)
        self.assertNotEqual(first.risk_instance_id, second.risk_instance_id)
        self.assertNotEqual(first.source_revision, second.source_revision)
        self.assertEqual("my009_uc_listing_20260410", second.source_batch_id)

    def test_engine_revision_changes_instance_identity_but_not_stable_risk_key(self):
        service = self._service()
        first = next(
            item
            for item in service.evaluate_subject_risks(PROJECT_ID, "S01003")
            if item.rule_id == "MY009-UC-IP-ADHERENCE-001"
        )
        try:
            service.risk_engine_version = lambda: "my009-monitoring-risk-v-next"
            second = next(
                item
                for item in service.evaluate_subject_risks(PROJECT_ID, "S01003")
                if item.rule_id == "MY009-UC-IP-ADHERENCE-001"
            )
        finally:
            del service.risk_engine_version

        self.assertEqual(first.risk_key, second.risk_key)
        self.assertNotEqual(first.risk_instance_id, second.risk_instance_id)
        self.assertEqual("my009-monitoring-risk-v-next", second.engine_version)

    def test_five_real_anchor_subjects_have_nonempty_source_grounded_drilldowns(self):
        for subject_id in sorted(ANCHOR_SUBJECTS):
            profile = self._service().subject_monitoring(PROJECT_ID, subject_id)
            self.assertEqual(subject_id, profile.subject_id)
            self.assertTrue(profile.timeline, subject_id)
            self.assertTrue(profile.efficacy_trends, subject_id)
            self.assertTrue(profile.safety_trends, subject_id)
            serialized = profile.model_dump_json()
            self.assertNotIn("/Users/", serialized)
            self.assertNotIn("RUX-", serialized)
            self.assertFalse(any(demo_id in serialized for demo_id in DEMO_SUBJECTS))

    def test_api_routes_canonicalize_my009_alias_and_fail_closed_for_unregistered_real_projects(self):
        client = TestClient(app)

        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            for route_id in [PROJECT_ID, "my009_uc_monitoring_raw"]:
                response = client.get(f"/api/projects/{route_id}/monitoring/subjects")
                self.assertEqual(200, response.status_code, response.text)
                self.assertEqual(26, response.json()["subject_count"])
                self.assertNotIn("demo_subject_monitoring_profiles", response.text)

            response = client.get(f"/api/projects/{PROJECT_ID}/subjects/S01003/monitoring")
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(PROJECT_ID, response.json()["project_id"])
            self.assertNotIn("/Users/", response.text)
            self.assertNotIn("已自动还原", response.text)

            unregistered = client.get("/api/projects/proj_d001/monitoring/subjects")
            self.assertEqual(404, unregistered.status_code, unregistered.text)
            self.assertNotIn("demo_subject_monitoring_profiles", unregistered.text)

            rux = client.get("/api/projects/proj_rux_03_002/monitoring/subjects")
            self.assertEqual(200, rux.status_code, rux.text)
            self.assertEqual(241, rux.json()["subject_count"])

    def test_my009_workbench_inbox_keeps_source_grounded_monitoring_items_in_cross_module_inbox(self):
        with self._isolated_my009_api_client() as client:
            response = client.get(f"/api/projects/{PROJECT_ID}/workbench-inbox?limit=50")
            payload = main_module.workbench_inbox_service.inbox(
                PROJECT_ID, actor="medical_manager", limit=50
            ).model_dump(mode="json")

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )
        self.assertEqual(PROJECT_ID, payload["project_id"])
        self.assertGreater(payload["total_open_count"], 0)
        self.assertTrue(payload["items"])
        monitoring_items = [item for item in payload["items"] if item["module"] == "medical_monitoring" and item["item_type"] == "risk"]
        self.assertTrue(monitoring_items)
        allowed_statuses = {"待医学复核", "已医学复核", "Query草稿", "已提交内部审批"}
        self.assertTrue(all(item["status"] in allowed_statuses for item in monitoring_items))
        self.assertTrue(any(item["status"] == "待医学复核" for item in monitoring_items))
        self.assertTrue(all(item["target_id"].startswith("S") for item in monitoring_items))
        for item in monitoring_items:
            refs = item["source_refs"]
            self.assertTrue(any(ref["locator"].startswith("listing:") for ref in refs))
            self.assertTrue(any(ref["locator"].startswith("docx:") for ref in refs))
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in ["/Users/", "已自动还原", "RUX-", *DEMO_SUBJECTS]:
            self.assertNotIn(forbidden, serialized)

    def test_my009_dashboard_reports_real_first_batch_and_monitoring_counts(self):
        with self._isolated_my009_api_client() as client:
            response = client.get(f"/api/projects/{PROJECT_ID}/dashboard")
            payload = main_module._my009_dashboard_summary().model_dump(mode="json")

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )
        self.assertEqual(PROJECT_ID, payload["project"]["project_id"])
        self.assertEqual("MY009-UC", payload["project"]["project_code"])
        self.assertEqual("my009_uc_listing_20260408", payload["latest_batch"]["batch_id"])
        self.assertEqual("first_batch_no_previous_baseline", payload["latest_batch"]["status"])
        self.assertIsNone(payload["latest_batch"]["previous_batch_id"])
        self.assertEqual(4106, payload["latest_batch"]["row_count"])
        self.assertEqual(26, payload["latest_batch"]["subject_count"])
        self.assertEqual(8, payload["latest_batch"]["site_count"])
        monitoring = next(item for item in payload["modules"] if item["module"] == "medical_monitoring")
        self.assertGreater(monitoring["open_risk_count"], 0)
        self.assertNotIn("/Users/", response.text)
        self.assertNotIn("RUX-", response.text)


if __name__ == "__main__":
    unittest.main()
