from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.evidence_design_manifest import CRSWNP_MASTER_ROOT, PNH_COMPETITOR_DB, EvidenceDesignManifestService  # noqa: E402
from services.api.app.evidence_picos_workflow import EvidencePicosDecisionStore, EvidencePicosWorkflowService  # noqa: E402
from services.api.app.evidence_picos_workflow import EvidencePicosApprovalService, SqliteEvidencePicosDecisionStore  # noqa: E402
from services.api.app.sqlite_runtime_store import RuntimeStoreError, SqliteRuntimeStore  # noqa: E402
from packages.contracts.workbench_contracts import (  # noqa: E402
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalState,
    AuditEvent,
)
from services.api.app.main import app  # noqa: E402


@unittest.skipUnless(CRSWNP_MASTER_ROOT.exists(), "CRSwNP evidence fixture path is unavailable")
class EvidencePicosWorkflowTests(unittest.TestCase):
    def build_service(self, tmp: str) -> EvidencePicosWorkflowService:
        return EvidencePicosWorkflowService(
            EvidenceDesignManifestService(),
            EvidencePicosDecisionStore(Path(tmp) / "picos_decisions.jsonl"),
        )

    def test_workflow_initializes_five_picos_steps_without_overclaim_or_lifecycle_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.build_service(tmp).workflow("proj_mgk10_crswnp")
            serialized = json.dumps(workflow.model_dump(mode="json"), ensure_ascii=False)

            self.assertEqual("证据调研与方案设计", workflow.module_label)
            self.assertEqual("PICOS 决策工作台", workflow.workflow_label)
            self.assertEqual(5, len(workflow.steps))
            self.assertEqual(0, workflow.decision_count)
            self.assertEqual(0, workflow.writing_candidate_count)
            self.assertTrue(all(step.options for step in workflow.steps))
            self.assertTrue(all(step.codex_runtime_dependency is False for step in workflow.steps))
            self.assertTrue(all(step.needs_medical_confirmation for step in workflow.steps))
            self.assertIn("作者确认", workflow.formal_output_boundary)
            self.assertNotIn("待医学批准", serialized)
            self.assertIn("PICOS完整性门", {gate.gate_label for gate in workflow.quality_gates})
            for forbidden in [
                "/Users/",
                "第2环节",
                "阶段2",
                "Stage 2",
                "已批准方案",
                "方案定稿",
                "可直接提交监管",
                "AI已确认",
                "疗效最优",
                "首选方案",
                "监管认可",
            ]:
                self.assertNotIn(forbidden, serialized)

    def test_picos_ai_boundary_requires_literal_boolean_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.build_service(tmp)
            with patch(
                "services.api.app.evidence_picos_workflow.ai_gateway_status_from_env",
                return_value={
                    "semantic_ai_tasks_enabled": "true",
                    "ai_gateway_status": "configured",
                },
            ):
                workflow = service.workflow("proj_mgk10_crswnp")

            ai_gate = next(
                gate
                for gate in workflow.quality_gates
                if gate.gate_id == "picos:gate:ai_boundary"
            )
            self.assertEqual("warning", ai_gate.status)
            self.assertEqual("not_configured", workflow.ai_gateway_status)

    def test_selection_or_saved_revision_is_the_single_author_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.build_service(tmp)
            package_id = service.workflow("proj_mgk10_crswnp").package_id
            question_id = "picos:outcomes"
            option_id = f"{question_id}:option:1"

            selected = service.apply_action(
                "proj_mgk10_crswnp",
                package_id,
                question_id,
                {"action": "select_option", "option_id": option_id},
            )
            step = next(item for item in selected.steps if item.question_id == question_id)
            self.assertEqual(option_id, step.selected_option_id)
            self.assertEqual("作者已确认", step.decision_status)
            self.assertEqual(1, selected.writing_candidate_count)
            self.assertEqual(
                "blocked",
                next(
                    gate
                    for gate in selected.quality_gates
                    if gate.gate_id == "picos:gate:completeness"
                ).status,
            )

            candidate = service.apply_action(
                "proj_mgk10_crswnp",
                package_id,
                question_id,
                {"action": "save_rationale", "user_rationale": "采用症状和客观鼻息肉双终点，便于兼顾患者获益和客观评价。"},
            )
            step = next(item for item in candidate.steps if item.question_id == question_id)
            self.assertEqual("作者已确认", step.decision_status)
            self.assertEqual("作者已确认，可进入写作交接", step.writing_handoff_status)
            self.assertEqual(2, len(step.audit_trail))

            restored = self.build_service(tmp).workflow("proj_mgk10_crswnp", package_id)
            restored_step = next(item for item in restored.steps if item.question_id == question_id)
            self.assertEqual("作者已确认", restored_step.decision_status)
            self.assertEqual(1, restored.writing_candidate_count)

    def test_endpoint_blocks_invalid_handoff_and_uses_business_module_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.build_service(tmp)
            client = TestClient(app)
            with patch("services.api.app.main.evidence_picos_workflow_service", service):
                response = client.get("/api/projects/proj_mgk10_crswnp/evidence-design/picos-workflow")
                self.assertEqual(200, response.status_code)
                payload = response.json()
                self.assertEqual("evidence_design", payload["module"])
                self.assertEqual("PICOS 决策工作台", payload["workflow_label"])

                package_id = payload["package_id"]
                question_id = "picos:population"
                blocked = client.post(
                    f"/api/projects/proj_mgk10_crswnp/evidence-design/picos-workflow/{package_id}/questions/{question_id}/actions",
                    json={"action": "mark_writing_candidate"},
                )
                self.assertEqual(409, blocked.status_code)
                self.assertIn("必须选择候选方案", blocked.json()["detail"])

                selected = client.post(
                    f"/api/projects/proj_mgk10_crswnp/evidence-design/picos-workflow/{package_id}/questions/{question_id}/actions",
                    json={
                        "action": "select_option",
                        "option_id": f"{question_id}:option:1",
                        "user_rationale": "目标人群先采用重度未控制候选，后续需医学总监确认阈值。",
                    },
                )
                self.assertEqual(200, selected.status_code)
                step = next(item for item in selected.json()["steps"] if item["question_id"] == question_id)
                self.assertEqual("作者已确认", step["decision_status"])

    @unittest.skipUnless(PNH_COMPETITOR_DB.exists(), "PNH evidence source is unavailable")
    def test_pnh_workflow_uses_indication_specific_questions_and_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.build_service(tmp).workflow("proj_my008_pnh_3_01")
            serialized = json.dumps(workflow.model_dump(mode="json"), ensure_ascii=False)

            self.assertEqual("pnh_competitive_evidence", workflow.package_id)
            self.assertEqual(5, len(workflow.steps))
            self.assertTrue(workflow.evidence_package_hash.startswith("sha256:"))
            self.assertIn("补体抑制剂", serialized)
            self.assertIn("Hb", serialized)
            self.assertIn("输血", serialized)
            for crswnp_term in ["CRSwNP", "鼻息肉", "NPS/NCS", "SNOT-22", "INCS"]:
                self.assertNotIn(crswnp_term, serialized)

    @unittest.skipUnless(PNH_COMPETITOR_DB.exists(), "PNH evidence source is unavailable")
    def test_sqlite_snapshot_approval_and_handoff_are_revision_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
            workflow_service = EvidencePicosWorkflowService(
                EvidenceDesignManifestService(),
                SqliteEvidencePicosDecisionStore(runtime),
            )
            approval_service = EvidencePicosApprovalService(workflow_service, runtime)
            project_id = "proj_my008_pnh_3_01"
            workflow = workflow_service.workflow(project_id)
            package_id = workflow.package_id

            for step in workflow.steps:
                workflow_service.apply_action(
                    project_id,
                    package_id,
                    step.question_id,
                    {
                        "action": "select_option",
                        "option_id": step.options[0].option_id,
                        "user_rationale": f"{step.picos_domain}采用第一候选，作为当前项目口径。",
                        "expected_revision": workflow_service.workflow(
                            project_id,
                            package_id,
                        ).revision,
                        "expected_evidence_package_hash": workflow.evidence_package_hash,
                        "idempotency_key": f"select-{step.question_id}",
                    },
                )

            ready = workflow_service.workflow(project_id, package_id)
            self.assertEqual(5, ready.revision)
            self.assertTrue(all(step.decision_status == "作者已确认" for step in ready.steps))
            self.assertEqual(1, ready.blocking_gate_count)
            self.assertEqual(
                ["picos:gate:author_confirmation"],
                [gate.gate_id for gate in ready.quality_gates if gate.status == "blocked"],
            )
            submitted = approval_service.submit_for_approval(
                project_id,
                package_id,
                {
                    "expected_revision": ready.revision,
                    "expected_evidence_package_hash": ready.evidence_package_hash,
                    "idempotency_key": "submit-pnh-r10",
                },
            )
            self.assertEqual(ApprovalState.MEDICALLY_APPROVED, submitted.workflow.approval_state)
            self.assertEqual("author_confirmation", submitted.snapshot.snapshot_type)
            self.assertEqual("author_confirmed", submitted.workflow.confirmation_status)
            approved_workflow = workflow_service.workflow(project_id, package_id)
            self.assertEqual(ApprovalState.MEDICALLY_APPROVED, approved_workflow.approval_state)
            self.assertEqual(5, approved_workflow.approved_revision)

            handoff = approval_service.create_handoff(
                project_id,
                package_id,
                {
                    "snapshot_id": submitted.snapshot.snapshot_id,
                    "idempotency_key": "handoff-author-confirmed",
                },
            )
            self.assertEqual("protocol", handoff.target_document_type)

            workflow_service.apply_action(
                project_id,
                package_id,
                ready.steps[0].question_id,
                {
                    "action": "reset_decision",
                    "expected_revision": 5,
                    "expected_evidence_package_hash": ready.evidence_package_hash,
                    "idempotency_key": "reset-after-approval",
                },
            )
            with self.assertRaises(RuntimeStoreError):
                approval_service.create_handoff(
                    project_id,
                    package_id,
                    {
                        "snapshot_id": submitted.snapshot.snapshot_id,
                        "idempotency_key": "handoff-stale-snapshot",
                    },
                )


if __name__ == "__main__":
    unittest.main()
