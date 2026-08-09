from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from services.api.app.main import app


def test_stale_monitoring_source_blocks_internal_approval_before_repository_write():
    repository = Mock()
    repository.approval.return_value = SimpleNamespace(
        target_type="medical_monitoring_risk_disposition"
    )
    inbox = Mock()
    inbox.require_current_monitoring_approval_source.side_effect = ValueError(
        "stale_source: current_monitoring_approval_id=approval_current"
    )

    with (
        patch("services.api.app.main.repo", repository),
        patch("services.api.app.main.workbench_inbox_service", inbox),
    ):
        response = TestClient(app).post(
            "/api/projects/proj_my009_uc/approvals/approval_old/actions",
            json={
                "action": "approve",
                "actor": "medical_manager",
                "comment": "不得批准旧来源版本。",
            },
        )

    assert response.status_code == 409
    assert "stale_source" in response.json()["detail"]
    inbox.require_current_monitoring_approval_source.assert_called_once_with(
        "proj_my009_uc",
        "approval_old",
    )
    repository.record_approval_action.assert_not_called()
