from types import SimpleNamespace

from services.api.app.monitoring_source_readiness import (
    resolve_monitoring_source_readiness,
    source_readiness_block_detail,
)


def test_active_manifest_states_are_readable_and_startable() -> None:
    for status in (
        "real_source_slice",
        "demo_available",
        "legacy_available",
        "active_demo",
        "available",
    ):
        readiness = resolve_monitoring_source_readiness(
            SimpleNamespace(implementation_status=status)
        )
        assert readiness is not None
        assert readiness.kind == "active"
        assert readiness.can_read is True
        assert readiness.can_start is True


def test_source_manifest_only_is_not_activation() -> None:
    readiness = resolve_monitoring_source_readiness(
        SimpleNamespace(implementation_status="source_manifest_only")
    )
    assert readiness is not None
    assert readiness.kind == "source_only"
    assert readiness.can_read is False
    assert readiness.can_start is False
    detail = source_readiness_block_detail(
        "proj_my008_pnh_3_02",
        readiness,
        operation="read",
    )
    assert detail["code"] == "medical_monitoring_source_not_activated"
    assert detail["project_id"] == "proj_my008_pnh_3_02"
    assert detail["readiness"] == {
        "kind": "source_only",
        "implementation_status": "source_manifest_only",
        "can_read": False,
        "can_start": False,
        "reason_code": "source_not_activated",
    }


def test_unknown_status_is_fail_closed_without_path_disclosure() -> None:
    readiness = resolve_monitoring_source_readiness(
        SimpleNamespace(implementation_status="source_inventory_slice")
    )
    assert readiness is not None
    assert readiness.kind == "unconfirmed"
    assert readiness.can_read is False
    assert readiness.can_start is False
    detail = source_readiness_block_detail(
        "proj_unknown",
        readiness,
        operation="write",
    )
    assert detail["code"] == "medical_monitoring_source_readiness_unconfirmed"
    assert "internal_path" not in str(detail)


def test_missing_binding_keeps_not_configured_handling() -> None:
    assert resolve_monitoring_source_readiness(None) is None
