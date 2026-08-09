from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from packages.contracts.workbench_contracts import ApprovalGate, ApprovalState
from services.api.app import main as app_main
from services.api.app.demo_repository import ApprovalRuntimeStore, DemoRepository


class SourceManifestDashboardApprovalOverlayTests(unittest.TestCase):
    def test_real_source_dashboard_projects_runtime_picos_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "demo.json"
            data_path.write_text(
                json.dumps(
                    {
                        "projects": [],
                        "approval_gates": [],
                        "approval_decisions": [],
                        "audit_events": [],
                        "subject_monitoring_profiles": [],
                    }
                ),
                encoding="utf-8",
            )
            store = ApprovalRuntimeStore(
                root / "gates.jsonl",
                root / "decisions.jsonl",
                root / "audits.jsonl",
            )
            project_id = "proj_mgk10_crswnp"
            now = datetime.now(timezone.utc)
            gate = ApprovalGate(
                approval_id="approval_picos_source_dashboard",
                project_id=project_id,
                target_type="evidence_picos_snapshot",
                target_id="picos_snapshot_source_dashboard",
                target_revision=12,
                state=ApprovalState.IN_MEDICAL_REVIEW,
                requested_by="medical_manager",
                created_at=now,
                updated_at=now,
            )
            store.upsert_gate(gate)
            repository = DemoRepository(data_path, approval_store=store)

            with patch.object(app_main, "repo", repository):
                dashboard = app_main._source_manifest_dashboard(project_id)

            self.assertEqual([gate.approval_id], [item.approval_id for item in dashboard.pending_approvals])
            counts = {item.module: item.pending_approval_count for item in dashboard.modules}
            self.assertEqual(1, counts["evidence_design"])
            self.assertEqual(0, counts["approvals"])

            store.upsert_gate(gate.model_copy(update={"state": ApprovalState.MEDICALLY_APPROVED}))
            with patch.object(app_main, "repo", repository):
                approved_dashboard = app_main._source_manifest_dashboard(project_id)
            self.assertEqual([], approved_dashboard.pending_approvals)


if __name__ == "__main__":
    unittest.main()
