from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import services.api.app.main as main_module
from services.api.app.main import app
from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringRole,
)
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)


class MonitoringRiskIndexApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @staticmethod
    def _principal(
        *,
        roles: tuple[MonitoringRole, ...] = (MonitoringRole.MEDICAL_MANAGER,),
    ) -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="legacy-read-test",
            tenant_id="tenant-kangzhe",
            roles=roles,
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="legacy-read-session",
            directory_revision="legacy-read-test-v1",
            verification_ref_sha256="f" * 64,
        )

    def test_legacy_risk_reads_bind_read_risk_audit_action(self) -> None:
        with (
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
            patch(
                "services.api.app.main.authorize_monitoring_action",
                wraps=main_module.authorize_monitoring_action,
            ) as authorize,
        ):
            response = self.client.get(
                "/api/projects/proj_rux_03_002/monitoring/risks",
                params={"page": 1, "page_size": 5},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, authorize.call_count)
        self.assertEqual(
            MonitoringAction.READ_RISK_AUDIT,
            authorize.call_args.args[1].action,
        )

    def test_legacy_workbench_and_ai_reads_bind_exact_actions(self) -> None:
        cases = (
            (
                "/api/projects/proj_rux_03_002/workbench-inbox",
                MonitoringAction.READ_WORKBENCH_INBOX,
            ),
            (
                "/api/projects/proj_rux_03_002/ai-runs/run-missing",
                MonitoringAction.READ_AI_RUN,
            ),
            (
                "/api/projects/proj_rux_03_002/ai-runs/run-missing/artifacts",
                MonitoringAction.READ_AI_ARTIFACT,
            ),
        )
        for path, expected_action in cases:
            with (
                self.subTest(path=path),
                patch(
                    "services.api.app.main.resolve_monitoring_principal_from_request",
                    return_value=self._principal(),
                ),
                patch(
                    "services.api.app.main.authorize_monitoring_action",
                    wraps=main_module.authorize_monitoring_action,
                ) as authorize,
                patch(
                    "services.api.app.main.project_source_manifest_service.is_user_created_project",
                    return_value=False,
                ),
            ):
                response = self.client.get(path)

            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_read_action_unconfigured",
                response.json()["detail"]["code"],
            )
            self.assertEqual(1, authorize.call_count)
            self.assertEqual(expected_action, authorize.call_args.args[1].action)

    def test_legacy_exact_read_actions_reject_medical_writer_before_access(self) -> None:
        writer = self._principal(roles=(MonitoringRole.MEDICAL_WRITER,))
        with (
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=writer,
            ),
            patch(
                "services.api.app.main.medical_monitoring_summary_service.current_risk_snapshot",
                side_effect=AssertionError("risk repository must not be touched"),
            ),
            patch(
                "services.api.app.main.workbench_inbox_service.inbox",
                side_effect=AssertionError("inbox service must not be touched"),
            ),
            patch(
                "services.api.app.main.ai_task_runner.artifacts",
                side_effect=AssertionError("AI artifact store must not be touched"),
            ),
            patch(
                "services.api.app.main.project_source_manifest_service.is_user_created_project",
                return_value=False,
            ),
        ):
            responses = (
                self.client.get(
                    "/api/projects/proj_rux_03_002/monitoring/risks",
                    params={"page": 1, "page_size": 5},
                ),
                self.client.get("/api/projects/proj_rux_03_002/workbench-inbox"),
                self.client.get(
                    "/api/projects/proj_rux_03_002/ai-runs/run-missing/artifacts"
                ),
            )

        for response in responses:
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_role_not_permitted",
                response.json()["detail"]["code"],
            )

    def test_legacy_get_and_dashboard_never_evaluate_or_persist_risks(self) -> None:
        with (
            patch(
                "services.api.app.main.rux_monitoring_service.evaluate_subject_risks",
                side_effect=AssertionError("read path must not evaluate risks"),
            ),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            response = self.client.get(
                "/api/projects/proj_rux_03_002/monitoring/risks",
                params={"page": 1, "page_size": 5},
            )
            dashboard = self.client.get("/api/projects/proj_rux_03_002/dashboard")

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(403, dashboard.status_code, dashboard.text)
        self.assertEqual(
            "monitoring_read_action_unconfigured",
            dashboard.json()["detail"]["code"],
        )
        payload = response.json()
        self.assertEqual("proj_rux_03_002", payload["project_id"])
        self.assertEqual(1, payload["page"])
        self.assertEqual(5, payload["page_size"])
        self.assertIn(
            payload["analysis_source"],
            {"persisted_snapshot", "persisted_snapshot_empty"},
        )
        self.assertNotIn(
            payload["analysis_source"],
            {"computed_transient", "computed_and_persisted"},
        )
        if payload["snapshot_status"] == "empty":
            self.assertEqual("", payload["snapshot_id"])
            self.assertEqual(0, payload["subjects_evaluated"])
            self.assertEqual(0, payload["total"])
            self.assertEqual([], payload["items"])
        else:
            self.assertTrue(payload["snapshot_id"].startswith("risksnap_"))
            self.assertGreaterEqual(payload["subjects_evaluated"], 0)
            self.assertGreaterEqual(payload["total"], len(payload["items"]))
            self.assertLessEqual(len(payload["items"]), 5)
            for risk in payload["items"]:
                self.assertTrue(risk["risk_key"].startswith("riskkey_"))
                self.assertTrue(
                    risk["risk_instance_id"].startswith("riskinst_")
                )
                self.assertNotIn("/Users/", str(risk))

        dashboard_payload = main_module._rux_dashboard_summary().model_dump(mode="json")
        medical_monitoring = next(
            item
            for item in dashboard_payload["modules"]
            if item["module"] == "medical_monitoring"
        )
        self.assertEqual(
            sum(dashboard_payload["risk_counts_by_severity"].values()),
            medical_monitoring["open_risk_count"],
        )

    def test_dashboard_read_fails_closed_before_summary_access(self) -> None:
        summary = Mock()
        with patch(
            "services.api.app.main._rux_dashboard_summary",
            summary,
        ):
            with patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=None,
            ):
                missing_principal = self.client.get(
                    "/api/projects/proj_rux_03_002/dashboard"
                )
            self.assertEqual(503, missing_principal.status_code)
            self.assertEqual(
                "monitoring_principal_unavailable",
                missing_principal.json()["detail"]["code"],
            )

            with patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ):
                scoped_principal = self.client.get(
                    "/api/projects/proj_rux_03_002/dashboard"
                )
            self.assertEqual(403, scoped_principal.status_code)
            self.assertEqual(
                "monitoring_read_action_unconfigured",
                scoped_principal.json()["detail"]["code"],
            )

        summary.assert_not_called()

    def test_subject_filter_reads_only_the_persisted_snapshot(self) -> None:
        with (
            patch(
                "services.api.app.main.rux_monitoring_service.evaluate_subject_risks",
                side_effect=AssertionError("subject filter must not evaluate risks"),
            ),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            response = self.client.get(
                "/api/projects/proj_rux_03_002/monitoring/risks",
                params={
                    "subject_id": "S01017",
                    "page": 1,
                    "page_size": 200,
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertNotIn(
            payload["analysis_source"],
            {"computed_transient", "computed_and_persisted"},
        )
        self.assertTrue(
            all(item["subject_id"] == "S01017" for item in payload["items"])
        )

    def test_legacy_direct_read_surfaces_fail_closed_without_server_principal(self) -> None:
        requests = [
            ("/api/projects/proj_rux_03_002/subjects/S01003/monitoring", None),
            ("/api/projects/proj_rux_03_002/monitoring/subjects", None),
            ("/api/projects/proj_rux_03_002/monitoring/risks", None),
            (
                "/api/projects/proj_rux_03_002/monitoring/risks/riskkey_missing/history",
                None,
            ),
            (
                "/api/projects/proj_rux_03_002/monitoring/risks/riskinst_missing/evidence-fragment",
                {"locator": "listing:missing"},
            ),
            ("/api/projects/proj_rux_03_002/monitoring/raw-intake", None),
            ("/api/projects/proj_rux_03_002/monitoring/batches", None),
            ("/api/projects/proj_rux_03_002/monitoring/batches/batch_missing", None),
            (
                "/api/projects/proj_rux_03_002/monitoring/batch-diff",
                {"previous_batch_id": "batch_previous", "current_batch_id": "batch_current"},
            ),
            (
                "/api/projects/proj_rux_03_002/monitoring/intake/session_missing",
                None,
            ),
            ("/api/projects/proj_rux_03_002/risks", None),
            ("/api/projects/proj_rux_03_002/data-batches", None),
            ("/api/projects/proj_rux_03_002/sources", None),
            ("/api/projects/proj_rux_03_002/source-contents", None),
            ("/api/projects/proj_rux_03_002/source-manifest", None),
            ("/api/projects/proj_rux_03_002/module-catalog", None),
            (
                "/api/projects/proj_rux_03_002/shared-protocol-facts",
                {"consumer": "medical_monitoring"},
            ),
        ]

        for path, params in requests:
            response = self.client.get(path, params=params)
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
                path,
            )

    def test_legacy_intake_writes_fail_closed_without_server_principal(self) -> None:
        responses = [
            self.client.post(
                "/api/projects/proj_mgk10_sar_demo/monitoring/intake",
                json={"extract_date": "2026-07-13", "sheets": []},
            ),
            self.client.post(
                "/api/projects/proj_rux_03_002/monitoring/batches/intake-file",
                params={
                    "filename": "listing.csv",
                    "idempotency_key": "no-principal-batch-intake",
                },
                content=b"",
            ),
            self.client.post(
                "/api/projects/proj_mgk10_sar_demo/monitoring/intake/file",
                params={
                    "filename": "listing.csv",
                    "extract_date": "2026-07-13",
                },
                content=b"",
            ),
        ]

        for response in responses:
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )

    def test_source_content_confirmation_fails_closed_without_server_principal(self) -> None:
        response = self.client.post(
            "/api/projects/proj_rux_03_002/sources/source_missing/content-validation/confirm",
            json={
                "reason": "等待服务器来源版本校验",
                "acknowledged_check_codes": ["file_role"],
                "expected_revision": 1,
                "idempotency_key": "no-principal-source-confirm",
            },
        )
        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )

    def test_source_content_confirmation_requires_data_management_role(self) -> None:
        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            response = self.client.post(
                "/api/projects/proj_rux_03_002/sources/source_missing/content-validation/confirm",
                json={
                    "reason": "当前 principal 没有来源版本校验角色",
                    "acknowledged_check_codes": ["file_role"],
                    "expected_revision": 1,
                    "idempotency_key": "manager-source-confirm-denied",
                },
            )
        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            "monitoring_role_not_permitted",
            response.json()["detail"]["code"],
        )

    @staticmethod
    def _risk_disposition_payload(**overrides):
        payload = {
            "action": "reviewed",
            "comment": "等待服务器身份与高风险复核证据",
            "expected_source_version": "missing-source-version",
        }
        payload.update(overrides)
        return payload

    def test_risk_disposition_writes_fail_closed_without_server_principal(self) -> None:
        responses = [
            self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/risk-disposition",
                json=self._risk_disposition_payload(),
            ),
            self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/rux-risk-disposition",
                json=self._risk_disposition_payload(),
            ),
        ]

        for response in responses:
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )

    def test_composite_workbench_inbox_read_and_mark_read_fail_closed(self) -> None:
        read_without_principal = self.client.get(
            "/api/projects/proj_rux_03_002/workbench-inbox"
        )
        mark_read_without_principal = self.client.post(
            "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/actions",
            json={
                "action": "mark_read",
                "actor": "client-spoof",
                "comment": "opened",
                "expected_source_version": "source-v1",
            },
        )
        self.assertEqual(503, read_without_principal.status_code, read_without_principal.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            read_without_principal.json()["detail"]["code"],
        )
        self.assertEqual(503, mark_read_without_principal.status_code, mark_read_without_principal.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            mark_read_without_principal.json()["detail"]["code"],
        )

        inbox_service = Mock()
        with (
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
            patch("services.api.app.main.workbench_inbox_service", inbox_service),
        ):
            read_with_principal = self.client.get(
                "/api/projects/proj_rux_03_002/workbench-inbox"
            )
            mark_read_with_principal = self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/actions",
                json={
                    "action": "mark_read",
                    "actor": "client-spoof",
                    "comment": "opened",
                    "expected_source_version": "source-v1",
                },
            )
        self.assertEqual(403, read_with_principal.status_code, read_with_principal.text)
        self.assertEqual(
            "monitoring_read_action_unconfigured",
            read_with_principal.json()["detail"]["code"],
        )
        self.assertEqual(403, mark_read_with_principal.status_code, mark_read_with_principal.text)
        self.assertEqual(
            "monitoring_write_action_unconfigured",
            mark_read_with_principal.json()["detail"]["code"],
        )
        inbox_service.inbox.assert_not_called()
        inbox_service.apply_action.assert_not_called()

    def test_risk_disposition_requires_high_risk_reauthentication_and_signature(self) -> None:
        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            reauth = self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/risk-disposition",
                json=self._risk_disposition_payload(),
            )
            signature = self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/rux-risk-disposition",
                json=self._risk_disposition_payload(reauthenticated=True),
            )

        self.assertEqual(403, reauth.status_code, reauth.text)
        self.assertEqual(
            "monitoring_reauthentication_required",
            reauth.json()["detail"]["code"],
        )
        self.assertEqual(403, signature.status_code, signature.text)
        self.assertEqual(
            "monitoring_electronic_signature_required",
            signature.json()["detail"]["code"],
        )

    def test_authorized_risk_disposition_uses_server_actor_before_service(self) -> None:
        service_result = Mock()
        service_result.model_dump.return_value = {"project_id": "proj_rux_03_002"}
        with (
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
            patch(
                "services.api.app.main.workbench_inbox_service.apply_monitoring_risk_disposition",
                return_value=service_result,
            ) as apply,
        ):
            response = self.client.post(
                "/api/projects/proj_rux_03_002/workbench-inbox/item_missing/risk-disposition",
                json=self._risk_disposition_payload(
                    actor="client-spoof",
                    reauthenticated=True,
                    signature_evidence_sha256="a" * 64,
                ),
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("proj_rux_03_002", response.json()["project_id"])
        called_request = apply.call_args.args[2]
        self.assertEqual("legacy-read-test", called_request.actor)

    def test_batch_validation_writes_fail_closed_without_server_principal(self) -> None:
        validation = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/validation-evidence",
            json={
                "mapping_revision": "mapping-v1",
                "mapping": {},
                "expected_domains": ["AE"],
                "full_snapshot_proof": {"confirmed": True},
                "expected_version": 1,
                "idempotency_key": "no-principal-validation",
            },
        )
        derived = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/verify-derived-snapshot",
            json={
                "expected_version": 1,
                "source_id": "source_missing",
                "source_content_sha256": "a" * 64,
                "original_source_class": "raw_snapshot_with_format_defect",
                "parser_version": "listing-parser-v1",
                "transformation_type": "parser_dimension_recovery",
                "execution_tool": "listing_file_parser",
                "execution_tool_version": "listing-parser-v1",
                "original_parse_sheets": [
                    {"sheet_name": "AE", "parsed_row_count": 1}
                ],
                "normalized_row_count": 1,
                "expected_domains": ["AE"],
                "verified_by": "client-actor",
                "reason": "等待服务器身份校验",
                "idempotency_key": "no-principal-derived",
            },
        )

        for response in (validation, derived):
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )

    def test_batch_lifecycle_policy_gaps_fail_closed_without_server_principal(self) -> None:
        confirm = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/confirm-full-snapshot",
            json={
                "expected_version": 1,
                "full_snapshot_proof": {"confirmed": True},
                "actor": "client-actor",
                "idempotency_key": "no-principal-full-snapshot",
            },
        )
        transition = self.client.post(
            "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/transition",
            json={
                "target_state": "parsed",
                "expected_version": 1,
                "idempotency_key": "no-principal-transition",
            },
        )

        for response in (confirm, transition):
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )

    def test_batch_lifecycle_policy_gaps_block_after_identity_scope_check(self) -> None:
        with (
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
            patch(
                "services.api.app.main.monitoring_mapping_batch_lifecycle_service.confirm_full_snapshot",
                side_effect=AssertionError("policy gap must block before lifecycle mutation"),
            ),
            patch(
                "services.api.app.main.monitoring_batch_service.transition",
                side_effect=AssertionError("policy gap must block before lifecycle mutation"),
            ),
        ):
            confirm = self.client.post(
                "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/confirm-full-snapshot",
                json={
                    "expected_version": 1,
                    "full_snapshot_proof": {"confirmed": True},
                    "actor": "client-actor",
                    "idempotency_key": "scoped-full-snapshot-gap",
                },
            )
            transition = self.client.post(
                "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/transition",
                json={
                    "target_state": "parsed",
                    "expected_version": 1,
                    "idempotency_key": "scoped-transition-gap",
                },
            )

        for response in (confirm, transition):
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_write_action_unconfigured",
                response.json()["detail"]["code"],
            )

    def test_batch_validation_actions_do_not_grant_unconfigured_manager_role(self) -> None:
        with patch(
            "services.api.app.main.resolve_monitoring_principal_from_request",
            return_value=self._principal(),
        ):
            validation = self.client.post(
                "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/validation-evidence",
                json={
                    "mapping_revision": "mapping-v1",
                    "mapping": {},
                    "expected_domains": ["AE"],
                    "full_snapshot_proof": {"confirmed": True},
                    "expected_version": 1,
                    "idempotency_key": "manager-validation-denied",
                },
            )
            derived = self.client.post(
                "/api/projects/proj_rux_03_002/monitoring/batches/batch_missing/verify-derived-snapshot",
                json={
                    "expected_version": 1,
                    "source_id": "source_missing",
                    "source_content_sha256": "a" * 64,
                    "original_source_class": "raw_snapshot_with_format_defect",
                    "parser_version": "listing-parser-v1",
                    "transformation_type": "parser_dimension_recovery",
                    "execution_tool": "listing_file_parser",
                    "execution_tool_version": "listing-parser-v1",
                    "original_parse_sheets": [
                        {"sheet_name": "AE", "parsed_row_count": 1}
                    ],
                    "normalized_row_count": 1,
                    "expected_domains": ["AE"],
                    "verified_by": "client-actor",
                    "reason": "等待服务器身份校验",
                    "idempotency_key": "manager-derived-denied",
                },
            )

        for response in (validation, derived):
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_role_not_permitted",
                response.json()["detail"]["code"],
            )


if __name__ == "__main__":
    unittest.main()
