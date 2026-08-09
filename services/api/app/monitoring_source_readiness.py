"""Fail-closed readiness contract for medical-monitoring source bindings.

The project manifest is allowed to register sources before a monitoring adapter
and independent-AI execution path have been accepted.  This small pure module
keeps that distinction explicit for both the module router and legacy routes;
it does not inspect source rows, call providers, or grant runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


SOURCE_MANIFEST_ONLY_IMPLEMENTATION_STATUS = "source_manifest_only"

# ``available`` is retained for focused router fixtures.  The remaining
# values are the only manifest states that currently represent an activated
# monitoring surface.  Unknown/planned/inventory states remain fail-closed.
ACTIVE_MONITORING_IMPLEMENTATION_STATUSES = frozenset(
    {
        "real_source_slice",
        "demo_available",
        "legacy_available",
        "active_demo",
        "available",
    }
)


@dataclass(frozen=True)
class MonitoringSourceReadiness:
    """Publicly safe readiness projection for one monitoring binding."""

    kind: str
    implementation_status: str
    can_read: bool
    can_start: bool
    reason_code: str

    def public_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "implementation_status": self.implementation_status,
            "can_read": self.can_read,
            "can_start": self.can_start,
            "reason_code": self.reason_code,
        }


def resolve_monitoring_source_readiness(
    binding: Any,
) -> Optional[MonitoringSourceReadiness]:
    """Resolve readiness without treating source registration as activation.

    ``None`` means no medical-monitoring binding is configured.  Callers keep
    their existing not-configured/legacy behavior in that case; a configured
    binding with any non-active status is explicitly blocked.
    """

    if binding is None:
        return None
    status = str(getattr(binding, "implementation_status", "") or "").strip()
    if status in ACTIVE_MONITORING_IMPLEMENTATION_STATUSES:
        return MonitoringSourceReadiness(
            kind="active",
            implementation_status=status,
            can_read=True,
            can_start=True,
            reason_code="activated",
        )
    if status == SOURCE_MANIFEST_ONLY_IMPLEMENTATION_STATUS:
        return MonitoringSourceReadiness(
            kind="source_only",
            implementation_status=status,
            can_read=False,
            can_start=False,
            reason_code="source_not_activated",
        )
    return MonitoringSourceReadiness(
        kind="unconfirmed",
        implementation_status=status,
        can_read=False,
        can_start=False,
        reason_code="readiness_unconfirmed",
    )


def source_readiness_block_detail(
    project_id: str,
    readiness: MonitoringSourceReadiness,
    *,
    operation: str,
) -> Dict[str, object]:
    """Build a redacted, stable HTTP detail payload for a blocked route."""

    if readiness.kind == "source_only":
        code = "medical_monitoring_source_not_activated"
        message = (
            "当前项目仅完成医学监查来源登记，尚未完成结构解析、适配器与独立AI激活；"
            "医学监查读取与执行已阻断。"
        )
    else:
        code = "medical_monitoring_source_readiness_unconfirmed"
        message = "当前项目医学监查来源状态未确认，读取与执行已阻断。"
    return {
        "code": code,
        "message": message,
        "project_id": project_id,
        "operation": operation,
        "readiness": readiness.public_dict(),
    }


__all__ = [
    "ACTIVE_MONITORING_IMPLEMENTATION_STATUSES",
    "MonitoringSourceReadiness",
    "SOURCE_MANIFEST_ONLY_IMPLEMENTATION_STATUS",
    "resolve_monitoring_source_readiness",
    "source_readiness_block_detail",
]
