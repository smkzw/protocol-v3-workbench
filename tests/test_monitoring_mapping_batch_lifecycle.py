from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.api.app.monitoring_batch_repository import MonitoringBatchRepository
from services.api.app.monitoring_batch_service import MonitoringBatchService
from services.api.app.monitoring_mapping_activation import (
    MonitoringBatchMappingBinding,
    MonitoringBatchMappingBindingResult,
    MonitoringBatchMappingBindingStatus,
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingActivationState,
    MonitoringMappingCapabilitySnapshot,
    MonitoringMappingCompatibilityReport,
    MonitoringMappingCompatibilityStatus,
)
from services.api.app.monitoring_mapping_batch_lifecycle import (
    MonitoringMappingBatchLifecycleService,
    MonitoringMappingDifferenceReviewRequired,
    MonitoringMappingRequiredError,
)


PROJECT_ID = "project-lifecycle"
MAPPING_REVISION = "monmaprev_" + "a" * 28


class _Field:
    def model_dump(self, **_kwargs):
        return {
            "domain": "AE",
            "source_field": "AETERM",
            "recommended_role": "adverse_event_term",
            "field_kind": "source_collected",
        }


class _MappingRepository:
    def get_revision(self, project_id: str, mapping_revision: str):
        assert project_id == PROJECT_ID
        assert mapping_revision == MAPPING_REVISION
        return SimpleNamespace(
            mapping_revision=MAPPING_REVISION,
            batch_id="batch-source",
            full_profile_sha256="b" * 64,
            fields=(_Field(),),
        )


class _ActivationService:
    def __init__(self, *, compatible: bool = True, available: bool = True):
        self.compatible = compatible
        self.available = available
        self.binding = None

    def get_active_mapping(self, project_id: str, validate_source: bool = True):
        assert project_id == PROJECT_ID
        if not self.available:
            raise MonitoringMappingActivationNotFoundError("missing")
        return MonitoringMappingActivationState(
            project_id=PROJECT_ID,
            mapping_revision=MAPPING_REVISION,
            mapping_content_sha256="c" * 64,
            source_batch_id="batch-source",
            source_profile_sha256="b" * 64,
            source_input_sha256="d" * 64,
            project_version=1,
            activated_by="medical-manager",
            activation_reason="confirmed",
            activated_at="2026-07-29T00:00:00+00:00",
            semantic_quality_report_sha256="f" * 64,
            capability_manifest_sha256="1" * 64,
            activation_disposition="activate_restricted",
            effective_capabilities_sha256="2" * 64,
            effective_capabilities=("raw_source_review",),
            capability_states=(
                MonitoringMappingCapabilitySnapshot(
                    capability_id="raw_source_review",
                    state="ready",
                    blocking_finding_group_ids=(),
                    limitation_codes=(),
                ),
                MonitoringMappingCapabilitySnapshot(
                    capability_id="lab_ctcae_rules",
                    state="blocked_by_quality",
                    blocking_finding_group_ids=("finding-lab",),
                    limitation_codes=("lab_lineage_incomplete",),
                ),
            ),
        )

    def get_batch_binding(self, project_id: str, batch_id: str):
        if self.binding is None:
            raise MonitoringMappingActivationNotFoundError("missing")
        return self.binding

    def compare_new_batch(self, project_id: str, profile):
        return self._report(profile)

    def register_batch_comparison(
        self,
        project_id: str,
        profile,
        *,
        expected_binding_version: int,
        actor: str,
        idempotency_key: str,
    ):
        report = self._report(profile)
        self.binding = MonitoringBatchMappingBinding(
            project_id=PROJECT_ID,
            batch_id=profile.batch_id,
            binding_version=expected_binding_version + 1,
            evaluated_mapping_revision=MAPPING_REVISION,
            mapping_content_sha256="c" * 64,
            profile_sha256=profile.profile_sha256,
            compatibility_report_sha256=report.report_sha256,
            status=(
                MonitoringBatchMappingBindingStatus.REUSE_SUGGESTED
                if self.compatible
                else MonitoringBatchMappingBindingStatus.DIFFERENCE_REVIEW_REQUIRED
            ),
            created_by=actor,
            created_at="2026-07-29T00:00:00+00:00",
        )
        return MonitoringBatchMappingBindingResult(
            binding=self.binding,
            report=report,
            replayed=False,
        )

    def _report(self, profile):
        status = (
            MonitoringMappingCompatibilityStatus.FULLY_COMPATIBLE
            if self.compatible
            else MonitoringMappingCompatibilityStatus.DIFFERENCE_REVIEW_REQUIRED
        )
        return MonitoringMappingCompatibilityReport(
            project_id=PROJECT_ID,
            batch_id=profile.batch_id,
            mapping_revision=MAPPING_REVISION,
            mapping_content_sha256="c" * 64,
            profile_sha256=profile.profile_sha256,
            status=status,
            reuse_recommended=self.compatible,
            added=(),
            missing=(),
            same_name_conflicts=(),
            report_sha256="e" * 64,
        )


def _parsed_batch(tmp_path: Path):
    repository = MonitoringBatchRepository(
        tmp_path / "batch.sqlite3",
        tmp_path / "objects",
    )
    source_path = tmp_path / "listing.xlsx"
    source_path.write_bytes(b"PK\x03\x04listing")
    source = repository.register_source(
        project_id=PROJECT_ID,
        source_entry_id="source-listing",
        validation_id="validation-listing",
        validation_revision=1,
        validator_version="source-content-v2",
        validation_use_status="allowed",
        role="edc_data_listing",
        source_class="raw_full_snapshot",
        file_path=source_path,
        parser_version="listing-parser-v1",
    )
    batch = repository.create_batch(
        project_id=PROJECT_ID,
        idempotency_key="create",
        expected_domains=("AE",),
    ).batch
    batch = repository.attach_source(
        batch_id=batch.batch_id,
        source_id=source.source_id,
        expected_version=batch.version,
        idempotency_key="attach",
    ).batch
    batch = repository.replace_rows(
        batch_id=batch.batch_id,
        rows=(
            {
                "business_key": "AE|S001|1",
                "domain": "AE",
                "data": {"SUBJID": "S001", "AETERM": "头痛"},
                "source_locator": {"sheet": "AE", "row": 2},
            },
        ),
        schema_fields=(
            {"domain": "AE", "field": "SUBJID", "source_sheet": "AE"},
            {"domain": "AE", "field": "AETERM", "source_sheet": "AE"},
        ),
        expected_version=batch.version,
        idempotency_key="rows",
    ).batch
    batch = repository.transition_batch(
        batch_id=batch.batch_id,
        target_state="parsed",
        expected_version=batch.version,
        idempotency_key="parsed",
    ).batch
    return repository, batch


def _service(tmp_path: Path, activation: _ActivationService):
    repository, batch = _parsed_batch(tmp_path)
    batch_service = MonitoringBatchService(None, repository)
    service = MonitoringMappingBatchLifecycleService(
        repository,
        batch_service,
        _MappingRepository(),
        activation,
    )
    return repository, batch, service


def test_confirm_full_snapshot_uses_server_mapping_and_freezes_batch(
    tmp_path: Path,
) -> None:
    repository, batch, service = _service(tmp_path, _ActivationService())

    result = service.confirm_full_snapshot(
        project_id=PROJECT_ID,
        batch_id=batch.batch_id,
        expected_version=batch.version,
        full_snapshot_proof={
            "confirmed": True,
            "basis": "完整 EDC 全量导出",
            "confirmed_by": "medical-manager",
        },
        actor="medical-manager",
        idempotency_key="confirm-full-snapshot",
    )

    assert result.batch["state"] == "frozen"
    assert result.mapping_revision == MAPPING_REVISION
    frozen = repository.load_diff_ready_batch(batch.batch_id)
    assert frozen.mapping_revision == MAPPING_REVISION
    contract = repository.load_frozen_mapping_contract(batch.batch_id)
    assert contract.schema_version == "monitoring_project_mapping_v2"
    assert contract.activation_disposition == "activate_restricted"
    assert contract.effective_capabilities == ("raw_source_review",)
    assert contract.capability_states[1]["state"] == "blocked_by_quality"


def test_missing_or_changed_mapping_stops_before_batch_validation(
    tmp_path: Path,
) -> None:
    _repository, batch, missing_service = _service(
        tmp_path / "missing",
        _ActivationService(available=False),
    )
    with pytest.raises(MonitoringMappingRequiredError):
        missing_service.confirm_full_snapshot(
            project_id=PROJECT_ID,
            batch_id=batch.batch_id,
            expected_version=batch.version,
            full_snapshot_proof={"confirmed": True},
            actor="medical-manager",
            idempotency_key="missing",
        )

    repository, changed_batch, changed_service = _service(
        tmp_path / "changed",
        _ActivationService(compatible=False),
    )
    with pytest.raises(MonitoringMappingDifferenceReviewRequired):
        changed_service.confirm_full_snapshot(
            project_id=PROJECT_ID,
            batch_id=changed_batch.batch_id,
            expected_version=changed_batch.version,
            full_snapshot_proof={"confirmed": True},
            actor="medical-manager",
            idempotency_key="changed",
        )
    assert repository.get_batch(changed_batch.batch_id).state == "parsed"
