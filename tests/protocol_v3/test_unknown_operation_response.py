"""An unclassified failure must not invite a duplicate mutation."""

import pytest
from fastapi import HTTPException

from app.protocol_workflow.api.router import _safe_call
from app.protocol_workflow.api.composition import _make_admission_dependency
from app.protocol_workflow.storage.sqlite import SqliteStorageConfigurationError


def test_unknown_operation_requests_reconciliation_before_retry():
    def unknown_result():
        raise RuntimeError("response interrupted after possible commit")

    with pytest.raises(HTTPException) as caught:
        _safe_call(unknown_result)

    assert caught.value.status_code == 500
    detail = caught.value.detail
    assert detail["can_retry"] is False
    assert "尚未确认" in detail["message"]
    assert "刷新" in detail["next_step"]
    assert "重复提交" in detail["next_step"]


def test_storage_unavailable_before_operation_has_actionable_response(monkeypatch):
    def unavailable(config, project_id):
        raise SqliteStorageConfigurationError("database unavailable")

    monkeypatch.setattr(
        "app.protocol_workflow.api.composition.is_project_admitted", unavailable
    )
    with pytest.raises(HTTPException) as caught:
        _make_admission_dependency({})("synthetic-study")
    assert caught.value.status_code == 503
    assert caught.value.detail["can_retry"] is False
    assert "未执行" in caught.value.detail["message"]
    assert "存储" in caught.value.detail["next_step"]


def test_corrupt_decision_ledger_requires_recovery_not_reconfirmation():
    from app.protocol_workflow.application.service import _LedgerRebuildError, _translate
    from app.protocol_workflow.errors import ProtocolErrorCode

    error = _translate(
        _LedgerRebuildError(event_id="event:synthetic", detail="missing decision effect"),
        project_id="proj:synthetic", object_id="sd:synthetic",
    )
    assert error.code == ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH
    assert error.retryable is False
    assert error.to_public_payload()["can_retry"] is False


def test_known_template_configuration_failure_is_a_failed_dependency():
    from app.protocol_workflow.application.service import _CurrentTemplateUnavailableError, _translate

    def unavailable():
        raise _translate(_CurrentTemplateUnavailableError("synthetic missing template"),
                         project_id="proj:synthetic", object_id="sd:synthetic")

    with pytest.raises(HTTPException) as caught:
        _safe_call(unavailable)
    assert caught.value.status_code == 424
    assert "未执行" in caught.value.detail["message"]
    assert "配置" in caught.value.detail["next_step"]
