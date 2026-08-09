"""Read-only service boundary for protocol/listing metric candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .monitoring_ai_field_profiler import MonitoringAIFieldProfiler
from .monitoring_batch_repository import (
    CompletenessGateError,
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
)
from .monitoring_metric_configuration import (
    MetricConfigurationBundle,
    build_metric_configuration_candidates,
)
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
)


@dataclass(frozen=True)
class MonitoringMetricConfigurationError(ValueError):
    """Stable HTTP-facing error for the read-only candidate endpoint."""

    code: str
    message: str
    http_status: int = 409

    def __str__(self) -> str:
        return self.message


class MonitoringMetricConfigurationService:
    """Join one protocol version to one complete frozen listing profile.

    The service deliberately owns no persistence and no confirmation path. It
    delegates all candidate semantics to ``build_metric_configuration_candidates``
    and returns its candidate-only bundle unchanged.
    """

    def __init__(
        self,
        *,
        protocol_repository: MonitoringProtocolRuleRepository,
        batch_repository: MonitoringBatchRepository,
        profiler: MonitoringAIFieldProfiler | None = None,
    ) -> None:
        self.protocol_repository = protocol_repository
        self.batch_repository = batch_repository
        self.profiler = profiler or MonitoringAIFieldProfiler(batch_repository)

    def build(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        batch_id: str,
    ) -> MetricConfigurationBundle:
        project = _required_text(project_id, "project_id")
        version_id = _required_text(protocol_version_id, "protocol_version_id")
        batch_key = _required_text(batch_id, "batch_id")

        try:
            version = self.protocol_repository.protocol_version(version_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            ) from exc
        if version.project_id != project:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            )

        try:
            batch = self.batch_repository.get_batch(batch_key)
        except MonitoringBatchRepositoryError as exc:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_batch_not_found",
                "当前项目未找到该 listing 批次。",
                http_status=404,
            ) from exc
        if batch.project_id != project:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_batch_not_found",
                "当前项目未找到该 listing 批次。",
                http_status=404,
            )

        try:
            profile = self.profiler.profile_frozen_batch(batch_key)
        except CompletenessGateError as exc:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_batch_not_frozen",
                "只有完整冻结的 listing 批次可以生成指标候选。",
                http_status=409,
            ) from exc
        except (MonitoringBatchRepositoryError, OSError, TypeError, ValueError) as exc:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_field_profile_unavailable",
                "当前 listing 批次的完整字段画像不可用。",
                http_status=409,
            ) from exc

        if profile.project_id != project or profile.batch_id != batch_key:
            raise MonitoringMetricConfigurationError(
                "monitoring_metric_field_profile_identity_mismatch",
                "字段画像与当前项目或 listing 批次不一致。",
                http_status=409,
            )

        facts = self.protocol_repository.facts_for_version(version_id)
        return build_metric_configuration_candidates(
            project_id=project,
            protocol_version_id=version_id,
            facts=facts,
            field_profile=profile,
        )


def metric_configuration_public_payload(
    bundle: MetricConfigurationBundle,
) -> dict[str, Any]:
    """Expose review metadata without implying confirmation or activation."""

    return {
        **bundle.model_dump(mode="json"),
        "medically_confirmed": bundle.medically_confirmed,
        "usable_candidate_count": bundle.usable_candidate_count,
        "review": {
            "candidate_only": bundle.status == "candidate_only",
            "requires_medical_confirmation": bool(bundle.candidates),
            "issue_count": len(bundle.issues),
        },
    }


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MonitoringMetricConfigurationError(
            "monitoring_metric_request_invalid",
            f"{field_name} 不能为空。",
            http_status=422,
        )
    return value.strip()


__all__ = [
    "MonitoringMetricConfigurationError",
    "MonitoringMetricConfigurationService",
    "metric_configuration_public_payload",
]
