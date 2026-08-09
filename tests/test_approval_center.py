from __future__ import annotations

import sys
import tempfile
import unittest
from hashlib import sha1
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import ApprovalAction, ApprovalActionRequest, ApprovalState  # noqa: E402
from services.api.app.demo_repository import ApprovalRuntimeStore, DemoRepository  # noqa: E402
import services.api.app.main as main_module  # noqa: E402
from services.api.app.main import app, repo as api_repo, workbench_inbox_service  # noqa: E402


class ApprovalCenterActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_approval_store = api_repo.approval_store
        runtime = Path(self.tmp.name) / "runtime"
        api_repo.approval_store = ApprovalRuntimeStore(
            runtime / "approval_gates.jsonl",
            runtime / "approval_decisions.jsonl",
            runtime / "approval_audit_events.jsonl",
        )
        api_repo._data = None
        self.client = TestClient(app)

    def tearDown(self):
        api_repo._data = None
        api_repo.approval_store = self.original_approval_store
        self.tmp.cleanup()

    def _new_runtime_repo(self):
        return DemoRepository(api_repo.data_path, approval_store=api_repo.approval_store)

    def test_approve_is_blocked_by_backend_when_quality_gate_has_blockers(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/approvals/approval_protocol_sec_objectives/actions",
            json={"action": "approve", "actor": "medical_manager", "comment": "证据已复核"},
        )

        self.assertEqual(409, response.status_code)
        result = response.json()["detail"]
        self.assertTrue(result["decision"]["blocked"])
        self.assertEqual("in_medical_review", result["decision"]["previous_state"])
        self.assertEqual("in_medical_review", result["decision"]["new_state"])
        self.assertEqual("in_medical_review", result["approval"]["state"])

        blocker_types = {item["blocker_type"] for item in result["blockers"]}
        self.assertIn("low_evidence_coverage", blocker_types)
        self.assertIn("quality_gate", blocker_types)
        self.assertIn("open_risk", blocker_types)
        self.assertNotIn("open_revision_thread", blocker_types)

        approval = api_repo.approval("proj_mgk10_sar_demo", "approval_protocol_sec_objectives")
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, approval.state)
        self.assertEqual("需补充终点选择依据后再批准。", approval.review_comments)
        self.assertEqual(1, len(api_repo.data["approval_decisions"]))
        self.assertEqual(1, len(api_repo.data["audit_events"]))
        self.assertEqual("approval.approve.blocked", api_repo.data["audit_events"][0]["action"])

    def test_approve_updates_state_when_demo_blockers_are_closed(self):
        for risk in api_repo.data["risk_cases"]:
            if risk["module"] == "medical_monitoring" and risk.get("source_batch_id") == "batch_003":
                risk["status"] = "closed"

        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/approvals/approval_medical_monitoring_batch003/actions",
            json={"action": "approve", "actor": "medical_manager", "comment": "风险均已关闭"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertFalse(result["decision"]["blocked"])
        self.assertEqual([], result["blockers"])
        self.assertEqual("medically_approved", result["approval"]["state"])
        self.assertEqual("medical_manager", result["approval"]["approved_by"])
        self.assertEqual("approval.approve", result["audit_event"]["action"])

    def test_return_for_revision_updates_state_and_records_audit(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/approvals/approval_medical_monitoring_batch003/actions",
            json={"action": "return_for_revision", "actor": "medical_manager", "comment": "请先关闭高风险项"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertFalse(result["decision"]["blocked"])
        self.assertEqual("ai_draft", result["decision"]["previous_state"])
        self.assertEqual("returned_for_revision", result["decision"]["new_state"])
        self.assertEqual("returned_for_revision", result["approval"]["state"])
        self.assertEqual("请先关闭高风险项", result["approval"]["review_comments"])
        self.assertEqual("approval.return_for_revision", api_repo.data["audit_events"][0]["action"])
        self.assertEqual("return_for_revision", api_repo.data["approval_decisions"][0]["action"])

    def test_reject_marks_approval_superseded_and_records_decision(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/approvals/approval_medical_monitoring_batch003/actions",
            json={"action": "reject", "actor": "medical_manager", "comment": "本批冻结包作废"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("superseded", result["approval"]["state"])
        self.assertEqual("superseded", result["decision"]["new_state"])
        self.assertEqual("approval.reject", result["audit_event"]["action"])
        self.assertEqual("本批冻结包作废", api_repo.approval("proj_mgk10_sar_demo", "approval_medical_monitoring_batch003").review_comments)

    def test_view_quality_gate_returns_blockers_without_state_change(self):
        response = self.client.post(
            "/api/projects/proj_mgk10_sar_demo/approvals/approval_medical_monitoring_batch003/actions",
            json={"action": "view_quality_gate", "actor": "medical_manager"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("ai_draft", result["approval"]["state"])
        self.assertEqual("ai_draft", result["decision"]["previous_state"])
        self.assertEqual("ai_draft", result["decision"]["new_state"])
        self.assertFalse(result["decision"]["blocked"])
        self.assertGreaterEqual(len(result["blockers"]), 1)
        self.assertEqual("approval.view_quality_gate", result["audit_event"]["action"])
        approval = api_repo.approval("proj_mgk10_sar_demo", "approval_medical_monitoring_batch003")
        self.assertIsNone(approval.reviewed_by)

    def test_rux_risk_disposition_approval_can_be_approved_without_closing_risk(self):
        target = next(
            item
            for item in workbench_inbox_service.inbox("proj_rux_03_002").items
            if item.module == "medical_monitoring" and item.item_type == "risk"
        )
        source_token = sha1(
            f"{target.item_id}:{target.source_version}".encode("utf-8")
        ).hexdigest()[:12]
        approval = api_repo.ensure_rux_disposition_approval_gate(
            project_id="proj_rux_03_002",
            risk_id=target.source_id,
            subject_id=target.target_id,
            rule_id=target.source_refs[0].source_id,
            requested_by="medical_manager",
            source_token=source_token,
        )

        blockers = api_repo.approval_blockers("proj_rux_03_002", approval.approval_id)
        self.assertEqual([], blockers)
        dashboard_before_response = self.client.get("/api/projects/proj_rux_03_002/dashboard")
        self.assertEqual(503, dashboard_before_response.status_code)
        self.assertEqual(
            "monitoring_principal_unavailable",
            dashboard_before_response.json()["detail"]["code"],
        )
        dashboard_before = main_module._rux_dashboard_summary().model_dump(mode="json")
        pending_ids = {item["approval_id"] for item in dashboard_before["pending_approvals"]}
        self.assertIn(approval.approval_id, pending_ids)

        response = self.client.post(
            f"/api/projects/proj_rux_03_002/approvals/{approval.approval_id}/actions",
            json={"action": "approve", "actor": "medical_manager", "comment": "仅批准内部Query草稿，待中心回复后再判断是否关闭风险。"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertFalse(result["decision"]["blocked"])
        self.assertEqual("in_medical_review", result["decision"]["previous_state"])
        self.assertEqual("medically_approved", result["decision"]["new_state"])
        self.assertEqual("medically_approved", result["approval"]["state"])
        self.assertEqual("medical_manager", result["approval"]["approved_by"])
        self.assertEqual("approval.approve", result["audit_event"]["action"])

        dashboard_response = self.client.get("/api/projects/proj_rux_03_002/dashboard")
        self.assertEqual(503, dashboard_response.status_code)
        self.assertEqual(
            "monitoring_principal_unavailable",
            dashboard_response.json()["detail"]["code"],
        )
        dashboard = main_module._rux_dashboard_summary().model_dump(mode="json")
        self.assertEqual([], dashboard["pending_approvals"])

    def test_rux_approval_actions_persist_across_repository_restart(self):
        scenarios = [
            (ApprovalAction.APPROVE, ApprovalState.MEDICALLY_APPROVED, "仅批准内部Query草稿/处置建议；不代表对外Query已执行、风险关闭或归档。"),
            (ApprovalAction.RETURN_FOR_REVISION, ApprovalState.RETURNED_FOR_REVISION, "内部Query草稿需补充ALT/AST与AE链路说明。"),
            (ApprovalAction.REJECT, ApprovalState.SUPERSEDED, "内部Query草稿证据不足，暂不进入对外流程。"),
        ]

        for index, (action, expected_state, comment) in enumerate(scenarios):
            with self.subTest(action=action.value):
                runtime = Path(self.tmp.name) / f"runtime_{index}"
                api_repo.approval_store = ApprovalRuntimeStore(
                    runtime / "approval_gates.jsonl",
                    runtime / "approval_decisions.jsonl",
                    runtime / "approval_audit_events.jsonl",
                )
                api_repo._data = None
                approval = api_repo.ensure_rux_disposition_approval_gate(
                    project_id="proj_rux_03_002",
                    risk_id=f"rux_s01017_alt_ast_5xuln_{index}",
                    subject_id="S01017",
                    rule_id="RUX-LAB-ALT-AST",
                    requested_by="medical_manager",
                )

                result = api_repo.record_approval_action(
                    "proj_rux_03_002",
                    approval.approval_id,
                    ApprovalActionRequest(action=action, actor="medical_manager", comment=comment),
                )
                self.assertEqual(expected_state, result.approval.state)

                restarted_repo = self._new_runtime_repo()
                recovered = restarted_repo.approval("proj_rux_03_002", approval.approval_id)
                self.assertEqual(expected_state, recovered.state)
                self.assertEqual("medical_manager", recovered.reviewed_by)
                if action == ApprovalAction.APPROVE:
                    self.assertEqual("medical_manager", recovered.approved_by)
                else:
                    self.assertIsNone(recovered.approved_by)
                self.assertEqual(comment, recovered.review_comments)
                self.assertNotRegex(recovered.review_comments, r"已发中心|风险已关闭|正式批准|自动关闭|可直接归档|监管归档完成|电子签名已完成")

                decisions = [
                    item
                    for item in restarted_repo.data["approval_decisions"]
                    if item["project_id"] == "proj_rux_03_002" and item["approval_id"] == approval.approval_id
                ]
                audit_events = [
                    item
                    for item in restarted_repo.data["audit_events"]
                    if item["project_id"] == "proj_rux_03_002" and item["target_id"] == approval.approval_id
                ]
                self.assertEqual(1, len(decisions))
                self.assertEqual(1, len(audit_events))
                self.assertEqual(action.value, decisions[0]["action"])
                self.assertEqual(f"approval.{action.value}", audit_events[0]["action"])

    def test_rux_view_quality_gate_persists_audit_without_mutating_gate(self):
        approval = api_repo.ensure_rux_disposition_approval_gate(
            project_id="proj_rux_03_002",
            risk_id="rux_s01017_alt_ast_5xuln_quality_gate",
            subject_id="S01017",
            rule_id="RUX-LAB-ALT-AST",
            requested_by="medical_manager",
        )

        result = api_repo.record_approval_action(
            "proj_rux_03_002",
            approval.approval_id,
            ApprovalActionRequest(action=ApprovalAction.VIEW_QUALITY_GATE, actor="medical_manager", comment=""),
        )
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, result.approval.state)

        restarted_repo = self._new_runtime_repo()
        recovered = restarted_repo.approval("proj_rux_03_002", approval.approval_id)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, recovered.state)
        self.assertIsNone(recovered.reviewed_by)
        self.assertIsNone(recovered.approved_by)
        self.assertIn("内部Query草稿/处置建议审批", recovered.review_comments)

        decisions = [
            item
            for item in restarted_repo.data["approval_decisions"]
            if item["project_id"] == "proj_rux_03_002" and item["approval_id"] == approval.approval_id
        ]
        audit_events = [
            item
            for item in restarted_repo.data["audit_events"]
            if item["project_id"] == "proj_rux_03_002" and item["target_id"] == approval.approval_id
        ]
        self.assertEqual(1, len(decisions))
        self.assertEqual(1, len(audit_events))
        self.assertEqual("view_quality_gate", decisions[0]["action"])
        self.assertEqual("approval.view_quality_gate", audit_events[0]["action"])


if __name__ == "__main__":
    unittest.main()
