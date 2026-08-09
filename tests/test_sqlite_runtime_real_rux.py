from __future__ import annotations

import gc
import json
import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalState,
    MonitoringMedicalJudgments,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
)
from services.api.app.demo_repository import DemoRepository
from services.api.app.rux_monitoring_service import RuxMonitoringService
from services.api.app.project_source_manifest import ProjectSourceManifestService
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore
from services.api.app.workbench_inbox import (
    RUX_PROJECT_ID,
    WorkbenchInboxService,
    WorkbenchInboxStore,
)
from tests.test_workbench_inbox import (
    FakeAiRunner,
    FakeEligibilityAdapter,
    FakePicosWorkflow,
    FakeSafetyHandoff,
    FakeSourceRegistry,
    FakeTflHandoff,
    FakeWritingManifest,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
RUX_MANIFEST = ProjectSourceManifestService(PROJECT_ROOT).build_manifest(RUX_PROJECT_ID)
RUX_LISTING = next(
    source.internal_path
    for source in RUX_MANIFEST.sources
    if source.source_id == "rux_listing_20250612"
)
RUX_PROTOCOL = next(
    source.internal_path
    for source in RUX_MANIFEST.sources
    if source.source_id == "rux_protocol_v1_3"
)


@unittest.skipUnless(
    RUX_LISTING.exists() and RUX_PROTOCOL.exists(),
    "RUX raw listing and protocol are unavailable",
)
class SqliteRuntimeRealRuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        demo_data_path = self.root / "demo_data" / "workbench_demo_v0_1.json"
        demo_data_path.parent.mkdir(parents=True, exist_ok=True)
        demo_data_path.write_text(
            (PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        self.db_path = self.root / "runtime" / "workbench_runtime.sqlite3"
        self.runtime_store = SqliteRuntimeStore(self.db_path)
        self.monitoring = RuxMonitoringService(RUX_LISTING, RUX_PROTOCOL)
        self.service = self._service(self.runtime_store)

    def tearDown(self):
        self.tmp.cleanup()

    def _service(
        self,
        runtime_store: SqliteRuntimeStore,
        monitoring: RuxMonitoringService | None = None,
    ) -> WorkbenchInboxService:
        repo = DemoRepository(
            self.root / "demo_data" / "workbench_demo_v0_1.json",
            approval_store=runtime_store,
        )
        return WorkbenchInboxService(
            repo,
            FakeAiRunner(),
            FakePicosWorkflow(),
            FakeTflHandoff(),
            FakeSafetyHandoff(),
            FakeWritingManifest(),
            FakeSourceRegistry(),
            FakeEligibilityAdapter(),
            WorkbenchInboxStore(self.root / "runtime" / "workbench_inbox_actions.jsonl"),
            rux_disposition_store=runtime_store,
            rux_monitoring_service=monitoring or self.monitoring,
        )

    def test_real_listing_and_protocol_risk_survives_full_transaction_and_restart(self):
        self.assertEqual([], self.runtime_store.records(RUX_PROJECT_ID))
        self.assertEqual([], self.runtime_store.gates(RUX_PROJECT_ID))
        self.assertEqual([], self.runtime_store.decisions(RUX_PROJECT_ID))

        protocol_rules = self.monitoring.protocol_rule_registry()["table4"]
        stop_rule = next(
            rule
            for rule in protocol_rules
            if rule["rule_id"] == "RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE"
        )
        self.assertEqual("docx:table:4:row:7", stop_rule["source_locator"])
        self.assertIn("停用研究药物", stop_rule["action"])

        inbox = self.service.inbox(RUX_PROJECT_ID, limit=20)
        target = next(
            item
            for item in inbox.items
            if item.target_id == "S01017"
            and any(
                ref.source_id == "RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE"
                for ref in item.source_refs
            )
        )
        self.assertEqual("S01017", target.target_id)
        self.assertTrue(
            any(
                ref.source_type == "listing_data_row" and "row:1863" in ref.locator
                for ref in target.source_refs
            )
        )
        self.assertTrue(
            any(
                ref.source_type == "protocol_rule" and "docx:table:4:row:7" in ref.locator
                for ref in target.source_refs
            )
        )

        actions = (
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.REVIEWED,
                medical_judgments=MonitoringMedicalJudgments(review_completed=True),
                actor="medical_manager",
                comment="已从原始listing核对ALT/AST、AE及试验药物变更链路。",
                expected_source_version=target.source_version,
                idempotency_key="real-rux-reviewed-001",
            ),
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.QUERY_DRAFT,
                actor="medical_manager",
                comment="请中心确认ALT/AST复测、AE记录及试验药物停用依据。",
                query_draft_text="请中心确认ALT/AST复测、AE记录及试验药物停用依据。",
                expected_source_version=target.source_version,
                idempotency_key="real-rux-query-001",
            ),
            RuxRiskDispositionActionRequest(
                action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
                actor="medical_manager",
                comment="提交内部Query草稿/处置建议审批，不代表对外Query已执行。",
                expected_source_version=target.source_version,
                idempotency_key="real-rux-submit-001",
            ),
        )
        for request in actions:
            self.service.apply_rux_risk_disposition(
                RUX_PROJECT_ID,
                target.item_id,
                request,
            )

        approval_id = self.runtime_store.records(RUX_PROJECT_ID)[-1].approval_ref
        result = self.service.repo.record_approval_action(
            RUX_PROJECT_ID,
            approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager",
                comment="仅批准内部Query草稿/处置建议，不代表对外Query已执行或风险关闭。",
                idempotency_key="real-rux-approval-001",
            ),
        )
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, result.approval.state)
        self.assertEqual([], self.runtime_store.verify_audit_chain(RUX_PROJECT_ID))

        del self.service
        del self.monitoring
        gc.collect()
        restarted_store = SqliteRuntimeStore(self.db_path)
        restarted = self._service(
            restarted_store,
            RuxMonitoringService(RUX_LISTING, RUX_PROTOCOL),
        )
        recovered_item = next(
            item
            for item in restarted.inbox(RUX_PROJECT_ID, limit=20).items
            if item.item_id == target.item_id
        )
        recovered_approval = restarted.repo.approval(RUX_PROJECT_ID, approval_id)
        self.assertEqual("已提交内部审批", recovered_item.status)
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, recovered_approval.state)
        self.assertEqual(3, len(restarted_store.records(RUX_PROJECT_ID)))
        self.assertEqual(1, len(restarted_store.decisions(RUX_PROJECT_ID)))
        public_payload = json.dumps(
            {
                "item": recovered_item.model_dump(mode="json"),
                "approval": recovered_approval.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        self.assertNotIn("/Users/", public_payload)
        self.assertNotIn("server_path", public_payload)


if __name__ == "__main__":
    unittest.main()
