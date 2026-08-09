from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .monitoring_ai_field_profiler import MonitoringAIFieldProfiler
from .monitoring_batch_repository import (
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
)
from .monitoring_batch_service import MonitoringBatchService
from .monitoring_mapping_activation import (
    MonitoringBatchMappingBinding,
    MonitoringBatchMappingBindingResult,
    MonitoringBatchMappingBindingStatus,
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingActivationService,
)
from .monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
)


class MonitoringMappingBatchLifecycleError(ValueError):
    pass


class MonitoringMappingRequiredError(MonitoringMappingBatchLifecycleError):
    pass


class MonitoringMappingDifferenceReviewRequired(
    MonitoringMappingBatchLifecycleError
):
    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        super().__init__("new batch fields require mapping review")


@dataclass(frozen=True)
class MonitoringBatchFinalizeResult:
    batch: dict[str, Any]
    mapping_revision: str
    mapping_project_version: int
    compatibility: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "mapping_revision": self.mapping_revision,
            "mapping_project_version": self.mapping_project_version,
            "compatibility": self.compatibility,
        }


class MonitoringMappingBatchLifecycleService:
    """Server-owned bridge from an active mapping to one frozen listing batch."""

    def __init__(
        self,
        batch_repository: MonitoringBatchRepository,
        batch_service: MonitoringBatchService,
        mapping_repository: MonitoringMappingDraftRepository,
        activation_service: MonitoringMappingActivationService,
    ):
        self.batch_repository = batch_repository
        self.batch_service = batch_service
        self.mapping_repository = mapping_repository
        self.activation_service = activation_service
        self.profiler = MonitoringAIFieldProfiler(batch_repository)

    def confirm_full_snapshot(
        self,
        *,
        project_id: str,
        batch_id: str,
        expected_version: int,
        full_snapshot_proof: Mapping[str, Any],
        actor: str,
        idempotency_key: str,
    ) -> MonitoringBatchFinalizeResult:
        batch = self.batch_repository.get_batch(batch_id)
        if batch.project_id != project_id:
            raise MonitoringBatchRepositoryError(
                "monitoring batch not found for project"
            )
        if batch.state != "parsed":
            raise MonitoringMappingBatchLifecycleError(
                "only a parsed batch can be confirmed as a comparison baseline"
            )
        if batch.version != expected_version:
            raise MonitoringMappingBatchLifecycleError(
                "batch version changed before confirmation"
            )
        try:
            active = self.activation_service.get_active_mapping(project_id)
        except MonitoringMappingActivationNotFoundError as exc:
            raise MonitoringMappingRequiredError(
                "请先完成本项目字段识别与校对。"
            ) from exc

        profile = self.profiler.profile_batch(batch_id)
        binding = self._current_or_new_binding(
            project_id=project_id,
            profile=profile,
            actor=actor,
            active_mapping_revision=active.mapping_revision,
        )
        if (
            binding.binding.status
            != MonitoringBatchMappingBindingStatus.REUSE_SUGGESTED
        ):
            raise MonitoringMappingDifferenceReviewRequired(
                binding.report.to_dict()
            )
        if binding.binding.evaluated_mapping_revision != active.mapping_revision:
            raise MonitoringMappingBatchLifecycleError(
                "active mapping changed during batch confirmation"
            )

        revision = self.mapping_repository.get_revision(
            project_id,
            active.mapping_revision,
        )
        mapping_payload = {
            "schema_version": "monitoring_project_mapping_v2",
            "mapping_revision": revision.mapping_revision,
            "mapping_content_sha256": active.mapping_content_sha256,
            "source_batch_id": revision.batch_id,
            "source_profile_sha256": revision.full_profile_sha256,
            "semantic_quality_report_sha256": (
                active.semantic_quality_report_sha256
            ),
            "capability_manifest_sha256": active.capability_manifest_sha256,
            "activation_disposition": active.activation_disposition,
            "effective_capabilities_sha256": (
                active.effective_capabilities_sha256
            ),
            "effective_capabilities": list(active.effective_capabilities),
            "capability_states": [
                item.to_dict() for item in active.capability_states
            ],
            "fields": [
                field.model_dump(mode="json") for field in revision.fields
            ],
        }
        evidence = self.batch_service.record_validation_evidence(
            batch_id=batch_id,
            mapping_revision=active.mapping_revision,
            mapping=mapping_payload,
            expected_domains=profile.expected_domains,
            full_snapshot_proof=dict(full_snapshot_proof),
            expected_version=batch.version,
            idempotency_key=f"{idempotency_key}:mapping",
        )
        current = evidence.batch
        for state in ("validated", "confirmed", "frozen"):
            current = self.batch_service.transition(
                batch_id=batch_id,
                target_state=state,
                expected_version=current.version,
                idempotency_key=f"{idempotency_key}:{state}",
            ).batch
        return MonitoringBatchFinalizeResult(
            batch=current.to_dict(),
            mapping_revision=active.mapping_revision,
            mapping_project_version=active.project_version,
            compatibility=binding.report.to_dict(),
        )

    def _current_or_new_binding(
        self,
        *,
        project_id: str,
        profile: Any,
        actor: str,
        active_mapping_revision: str,
    ) -> MonitoringBatchMappingBindingResult:
        existing: MonitoringBatchMappingBinding | None = None
        try:
            existing = self.activation_service.get_batch_binding(
                project_id,
                profile.batch_id,
            )
        except MonitoringMappingActivationNotFoundError:
            pass
        if (
            existing is not None
            and existing.profile_sha256 == profile.profile_sha256
            and existing.evaluated_mapping_revision == active_mapping_revision
        ):
            report = self.activation_service.compare_new_batch(
                project_id,
                profile,
            )
            return MonitoringBatchMappingBindingResult(
                binding=existing,
                report=report,
                replayed=True,
            )
        return self.activation_service.register_batch_comparison(
            project_id,
            profile,
            expected_binding_version=(
                existing.binding_version if existing is not None else 0
            ),
            actor=actor,
            idempotency_key=(
                f"bind-{profile.batch_id[-24:]}-"
                f"{profile.profile_sha256[:16]}-"
                f"{active_mapping_revision[-12:]}"
            ),
        )
