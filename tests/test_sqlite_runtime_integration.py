from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalState,
    MonitoringMedicalJudgments,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
)
from services.api.app.demo_repository import DemoRepository  # noqa: E402
from services.api.app.medical_risk_repository import MedicalRiskRepository  # noqa: E402
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore  # noqa: E402
from services.api.app.workbench_inbox import (  # noqa: E402
    RUX_PROJECT_ID,
    WorkbenchInboxService,
    WorkbenchInboxStore,
)
from tests.test_workbench_inbox import (  # noqa: E402
    FakeAiRunner,
    FakeEligibilityAdapter,
    FakePicosWorkflow,
    FakeRuxMonitoringService,
    FakeSafetyHandoff,
    FakeSourceRegistry,
    FakeTflHandoff,
    FakeWritingManifest,
)


class SqliteRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.demo_data_path = self.root / "demo_data" / "workbench_demo_v0_1.json"
        self.demo_data_path.parent.mkdir(parents=True, exist_ok=True)
        self.demo_data_path.write_text(
            (PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.db_path = self.root / "runtime" / "workbench_runtime.sqlite3"
        self.read_store = WorkbenchInboxStore(self.root / "runtime" / "workbench_inbox_actions.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _rux_snapshot_repository(self, runtime_store, adapter) -> MedicalRiskRepository:
        """Self-contained RUX risk snapshot (the shared demo file carries no
        RUX project, so the flow cannot rely on demo_data content)."""
        repository = MedicalRiskRepository(self.root / "runtime" / "medical_risks_rux.sqlite3")
        subject_ids = adapter.subject_ids()
        risk_groups = [
            adapter.evaluate_subject_risks(RUX_PROJECT_ID, subject_id)
            for subject_id in subject_ids
        ]
        repository.save_snapshot(
            project_id=RUX_PROJECT_ID,
            source_revision=adapter.source_revision(),
            rule_profile_revision=adapter.risk_profile_revision(),
            engine_version=adapter.risk_engine_version(),
            evaluated_subject_count=len(subject_ids),
            risks=[risk for group in risk_groups for risk in group],
        )
        return repository

    def service(self, runtime_store):
        repo = DemoRepository(self.demo_data_path, approval_store=runtime_store)
        rux_monitoring = FakeRuxMonitoringService()
        return WorkbenchInboxService(
            repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(),
            FakeEligibilityAdapter(),
            self.read_store,
            rux_disposition_store=runtime_store,
            rux_monitoring_service=rux_monitoring,
            medical_risk_repository=self._rux_snapshot_repository(runtime_store, rux_monitoring),
        )

    def advance_to_query_draft(self, service):
        target = next(
            item
            for item in service.inbox(RUX_PROJECT_ID).items
            if item.title == "S01017 ALT/AST >5xULN"
        )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已核对ALT/AST、AE与试验药物变更链路。",
                expected_source_version=target.source_version,
            ),
        )
        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                query_draft_text="请中心确认ALT/AST升高是否已记录AE，并说明试验药物暂停/恢复依据。",
                expected_source_version=target.source_version,
            ),
        )
        return target

    def submit_for_approval(self, service, target):
        return service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交内部Query草稿/处置建议审批，不代表对外Query已执行。",
                expected_source_version=target.source_version,
            ),
        )

    def test_rux_submission_and_approval_action_use_one_sqlite_store(self):
        runtime_store = SqliteRuntimeStore(self.db_path)
        service = self.service(runtime_store)
        target = self.advance_to_query_draft(service)

        submitted = self.submit_for_approval(service, target)
        submitted_item = next(item for item in submitted.items if item.item_id == target.item_id)
        approval_id = runtime_store.records(RUX_PROJECT_ID)[-1].approval_ref

        self.assertEqual("已提交内部审批", submitted_item.status)
        self.assertEqual(3, len(runtime_store.records(RUX_PROJECT_ID)))
        self.assertEqual(1, len(runtime_store.gates(RUX_PROJECT_ID)))
        self.assertEqual(approval_id, runtime_store.gates(RUX_PROJECT_ID)[0].approval_id)

        result = service.repo.record_approval_action(
            RUX_PROJECT_ID,
            approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager",
                comment="仅批准内部Query草稿/处置建议；不代表对外Query已执行、风险关闭或归档。",
                idempotency_key="approve-rux-risk-001",
            ),
        )

        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, result.approval.state)
        self.assertEqual(1, len(runtime_store.audit_events(RUX_PROJECT_ID)))
        self.assertEqual(1, len(runtime_store.decisions(RUX_PROJECT_ID)))
        replay = service.repo.record_approval_action(
            RUX_PROJECT_ID,
            approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager",
                comment="仅批准内部Query草稿/处置建议；不代表对外Query已执行、风险关闭或归档。",
                idempotency_key="approve-rux-risk-001",
            ),
        )
        self.assertEqual(result.decision, replay.decision)
        self.assertEqual(result.audit_event, replay.audit_event)
        self.assertEqual(1, len(runtime_store.audit_events(RUX_PROJECT_ID)))
        self.assertEqual(1, len(runtime_store.decisions(RUX_PROJECT_ID)))
        restarted = self.service(SqliteRuntimeStore(self.db_path))
        recovered = restarted.repo.approval(RUX_PROJECT_ID, approval_id)
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, recovered.state)

    def test_submission_fault_does_not_leave_orphan_gate(self):
        normal_store = SqliteRuntimeStore(self.db_path)
        normal_service = self.service(normal_store)
        target = self.advance_to_query_draft(normal_service)

        def fail(checkpoint):
            if checkpoint == "after_gate":
                raise RuntimeError("fault:after_gate")

        failing_store = SqliteRuntimeStore(self.db_path, fault_injector=fail)
        failing_service = self.service(failing_store)

        with self.assertRaisesRegex(RuntimeError, "after_gate"):
            self.submit_for_approval(failing_service, target)

        self.assertEqual([], failing_store.gates(RUX_PROJECT_ID))
        self.assertEqual(2, len(failing_store.records(RUX_PROJECT_ID)))
        recovered_item = next(
            item
            for item in failing_service.inbox(RUX_PROJECT_ID).items
            if item.item_id == target.item_id
        )
        self.assertEqual("Query草稿", recovered_item.status)

    def test_duplicate_submission_replays_before_state_transition_validation(self):
        runtime_store = SqliteRuntimeStore(self.db_path)
        service = self.service(runtime_store)
        target = self.advance_to_query_draft(service)

        first = self.submit_for_approval(service, target)
        replay = self.submit_for_approval(service, target)

        first_item = next(item for item in first.items if item.item_id == target.item_id)
        replay_item = next(item for item in replay.items if item.item_id == target.item_id)
        self.assertEqual("已提交内部审批", first_item.status)
        self.assertEqual(first_item.status, replay_item.status)
        self.assertEqual(3, len(runtime_store.records(RUX_PROJECT_ID)))
        self.assertEqual(1, len(runtime_store.gates(RUX_PROJECT_ID)))

    def test_approval_action_fault_does_not_mutate_runtime_overlay(self):
        normal_store = SqliteRuntimeStore(self.db_path)
        normal_service = self.service(normal_store)
        target = self.advance_to_query_draft(normal_service)
        self.submit_for_approval(normal_service, target)
        approval_id = normal_store.records(RUX_PROJECT_ID)[-1].approval_ref

        def fail(checkpoint):
            if checkpoint == "after_audit":
                raise RuntimeError("fault:after_audit")

        failing_store = SqliteRuntimeStore(self.db_path, fault_injector=fail)
        failing_service = self.service(failing_store)

        with self.assertRaisesRegex(RuntimeError, "after_audit"):
            failing_service.repo.record_approval_action(
                RUX_PROJECT_ID,
                approval_id,
                ApprovalActionRequest(
                    action=ApprovalAction.APPROVE,
                    actor="medical_manager",
                    comment="仅批准内部Query草稿/处置建议。",
                ),
            )

        recovered = failing_service.repo.approval(RUX_PROJECT_ID, approval_id)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, recovered.state)
        self.assertEqual([], failing_store.audit_events(RUX_PROJECT_ID))
        self.assertEqual([], failing_store.decisions(RUX_PROJECT_ID))

    def test_stale_source_and_invalid_transition_rejections_are_audited(self):
        runtime_store = SqliteRuntimeStore(self.db_path)
        service = self.service(runtime_store)
        target = next(
            item
            for item in service.inbox(RUX_PROJECT_ID).items
            if item.title == "S01017 ALT/AST >5xULN"
        )

        with self.assertRaisesRegex(ValueError, "stale_source"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                    actor="medical_manager",
                    comment="使用过期数据批次尝试复核。",
                    expected_source_version="obsolete-source-version",
                    idempotency_key="stale-source-attempt-001",
                ),
            )

        service.apply_rux_risk_disposition(
            RUX_PROJECT_ID,
            target.item_id,
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="完成首次医学复核。",
                expected_source_version=target.source_version,
                idempotency_key="reviewed-attempt-001",
            ),
        )
        with self.assertRaisesRegex(ValueError, "already medically reviewed"):
            service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                RuxRiskDispositionActionRequest(
                    action=RuxRiskDispositionAction.REVIEWED,
                    medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                    actor="medical_manager",
                    comment="重复执行已完成的状态迁移。",
                    expected_source_version=target.source_version,
                    idempotency_key="invalid-transition-attempt-001",
                ),
            )

        rejection_types = {
            event["event_type"]
            for event in runtime_store.runtime_audit_records(RUX_PROJECT_ID)
        }
        self.assertIn("stale_source_rejected", rejection_types)
        self.assertIn("invalid_transition_rejected", rejection_types)


if __name__ == "__main__":
    unittest.main()
