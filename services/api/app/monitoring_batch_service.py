from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Mapping

from .listing_file_parser import LISTING_PARSER_VERSION, parse_listing_file
from .monitoring_batch_diff import (
    diff_monitoring_batches,
    listing_schema_fields,
    normalize_listing_sheets,
)
from .monitoring_batch_repository import (
    BatchMutationResult,
    DerivedSnapshotVerificationResult,
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
    RepositoryIntegrityError,
    SourceRegistration,
)
from .monitoring_source_classifier import (
    MonitoringSourceClassification,
    classify_monitoring_listing,
)

MONITORING_SOURCE_CLASSIFICATION_VERSION = "monitoring_source_classifier.v2"


class MonitoringBatchIntakeBlocked(ValueError):
    def __init__(self, code: str, detail: Mapping[str, Any]):
        self.code = code
        self.detail = dict(detail)
        super().__init__(code)


@dataclass(frozen=True)
class MonitoringBatchIntakeResult:
    source_entry_id: str
    validation: dict[str, Any]
    classification: MonitoringSourceClassification
    source: SourceRegistration
    batch: BatchMutationResult
    observed_domains: tuple[str, ...]
    row_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_entry_id": self.source_entry_id,
            "validation": dict(self.validation),
            "classification": self.classification.to_dict(),
            "source": self.source.to_dict(),
            "batch": self.batch.to_dict(),
            "observed_domains": list(self.observed_domains),
            "row_count": self.row_count,
        }


class MonitoringBatchService:
    """Project-neutral intake orchestration over shared source and batch stores."""

    def __init__(self, source_registry: Any, repository: MonitoringBatchRepository):
        self.source_registry = source_registry
        self.repository = repository

    def intake_listing(
        self,
        *,
        project_id: str,
        filename: str,
        content: bytes,
        idempotency_key: str,
        classification_override_reason: str = "",
    ) -> MonitoringBatchIntakeResult:
        if not content:
            raise ValueError("uploaded listing file is empty")
        sheets = parse_listing_file(filename, content)
        classification = classify_monitoring_listing(filename, sheets)
        registered = self.source_registry.register_listing_file(
            project_id,
            filename,
            content,
            module="medical_monitoring",
            expected_file_role="edc_data_listing",
            parsed_sheets=sheets,
        )
        validation = self.source_registry.current_content_validation(
            project_id,
            registered.entry.entry_id,
        )
        if validation is None:
            raise MonitoringBatchIntakeBlocked(
                "source_validation_unavailable",
                {
                    "source_entry_id": registered.entry.entry_id,
                    "message": "来源内容校验尚未生成，不能创建医学监查业务批次。",
                },
            )
        if validation.use_status not in {"allowed", "confirmed_after_warning"}:
            raise MonitoringBatchIntakeBlocked(
                "source_content_confirmation_required",
                {
                    "source_entry_id": registered.entry.entry_id,
                    "validation": validation.model_dump(mode="json"),
                },
            )
        if classification.technical_status != "passed":
            raise MonitoringBatchIntakeBlocked(
                "listing_technical_failure",
                {"classification": classification.to_dict()},
            )
        override_reason = classification_override_reason.strip()
        if classification.content_warnings and not override_reason:
            raise MonitoringBatchIntakeBlocked(
                "listing_classification_confirmation_required",
                {
                    "source_entry_id": registered.entry.entry_id,
                    "classification": classification.to_dict(),
                    "message": "该文件可继续导入，但需确认其来源分类；确认不会改变原分类。",
                },
            )

        normalized_rows = normalize_listing_sheets(sheets)
        schema_fields = listing_schema_fields(sheets)
        if not normalized_rows:
            raise MonitoringBatchIntakeBlocked(
                "listing_has_no_normalizable_rows",
                {"classification": classification.to_dict()},
            )
        observed_domains = tuple(sorted({
            str(row["domain"]).strip().upper() for row in normalized_rows
        } | {
            str(field["domain"]).strip().upper() for field in schema_fields
        }))
        del sheets
        validation_warnings = tuple(
            check.label
            for check in validation.checks
            if check.outcome in {"warning", "mismatch"}
        )
        content_warnings = tuple(
            dict.fromkeys(
                [*classification.content_warnings, *validation_warnings]
            )
        )
        medical_reason = (
            override_reason
            or validation.confirmation_reason.strip()
            or None
        )

        suffix = Path(filename or "listing.xlsx").suffix or ".xlsx"
        with NamedTemporaryFile(suffix=suffix) as handle:
            handle.write(content)
            handle.flush()
            source = self.repository.register_source(
                project_id=project_id,
                source_entry_id=registered.entry.entry_id,
                validation_id=validation.validation_id,
                validation_revision=validation.revision,
                validator_version=validation.validator_version,
                validation_use_status=validation.use_status,
                role="edc_data_listing",
                source_class=classification.source_class,
                file_path=Path(handle.name),
                file_name=Path(filename).name,
                parser_version=LISTING_PARSER_VERSION,
                classification_version=MONITORING_SOURCE_CLASSIFICATION_VERSION,
                technical_status="passed",
                content_warnings=content_warnings,
                medical_override_reason=medical_reason,
            )
        if source.content_sha256 != registered.entry.content_hash:
            raise RuntimeError("batch object hash does not match shared source registry")

        created = self.repository.create_batch(
            project_id=project_id,
            idempotency_key=f"{idempotency_key}:create",
            expected_domains=observed_domains,
        )
        attached = self.repository.attach_source(
            batch_id=created.batch.batch_id,
            source_id=source.source_id,
            expected_version=created.batch.version,
            idempotency_key=f"{idempotency_key}:attach",
        )
        materialized = self.repository.replace_rows(
            batch_id=created.batch.batch_id,
            rows=normalized_rows,
            schema_fields=schema_fields,
            expected_version=attached.batch.version,
            idempotency_key=f"{idempotency_key}:rows",
        )
        return MonitoringBatchIntakeResult(
            source_entry_id=registered.entry.entry_id,
            validation=validation.model_dump(mode="json"),
            classification=classification,
            source=source,
            batch=materialized,
            observed_domains=observed_domains,
            row_count=len(normalized_rows),
        )

    def record_validation_evidence(
        self,
        *,
        batch_id: str,
        mapping_revision: str,
        mapping: Mapping[str, Any],
        expected_domains: Iterable[str],
        full_snapshot_proof: Mapping[str, Any],
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        return self.repository.record_validation_evidence(
            batch_id=batch_id,
            mapping_revision=mapping_revision,
            mapping=mapping,
            expected_domains=expected_domains,
            full_snapshot_proof=full_snapshot_proof,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def verify_derived_snapshot(
        self,
        *,
        batch_id: str,
        source_id: str,
        source_content_sha256: str,
        original_source_class: str,
        parser_version: str,
        transformation_type: str,
        execution_tool: str,
        execution_tool_version: str,
        original_parse_sheets: Iterable[Mapping[str, Any]],
        normalized_row_count: int,
        expected_domains: Iterable[str],
        verified_by: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> DerivedSnapshotVerificationResult:
        source = self.repository.get_source(source_id)
        original_bytes = self.repository.read_source_bytes(source_id)
        reproduced_hash = sha256(original_bytes).hexdigest()
        if reproduced_hash != source_content_sha256:
            raise RepositoryIntegrityError(
                "source content hash does not match the saved original parent file"
            )
        if source.parser_version != parser_version:
            raise RepositoryIntegrityError(
                "parser_version does not match source registration"
            )
        if parser_version != LISTING_PARSER_VERSION:
            raise RepositoryIntegrityError(
                "derived snapshot verification requires the current recovery parser version"
            )
        if execution_tool != "listing_file_parser":
            raise ValueError("execution_tool must be listing_file_parser")
        if execution_tool_version != LISTING_PARSER_VERSION:
            raise ValueError(
                "execution_tool_version must match the current recovery parser"
            )

        reproduced_sheets = parse_listing_file(source.file_name, original_bytes)
        reproduced_classification = classify_monitoring_listing(
            source.file_name,
            reproduced_sheets,
        )
        if (
            reproduced_classification.source_class
            != "raw_snapshot_with_format_defect"
        ):
            raise RepositoryIntegrityError(
                "original source bytes do not reproduce a worksheet dimension format defect"
            )
        observed_parse_sheets = tuple(
            {
                "sheet_name": sheet.sheet_name,
                "parsed_row_count": len(sheet.rows),
            }
            for sheet in reproduced_sheets
        )
        return self.repository.verify_derived_snapshot(
            batch_id=batch_id,
            source_id=source_id,
            source_content_sha256=source_content_sha256,
            original_source_class=original_source_class,
            parser_version=parser_version,
            transformation_type=transformation_type,
            execution_tool=execution_tool,
            execution_tool_version=execution_tool_version,
            original_parse_sheets=original_parse_sheets,
            observed_original_parse_sheets=observed_parse_sheets,
            observed_original_source_class=reproduced_classification.source_class,
            normalized_row_count=normalized_row_count,
            expected_domains=expected_domains,
            verified_by=verified_by,
            reason=reason,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def transition(
        self,
        *,
        batch_id: str,
        target_state: str,
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        return self.repository.transition_batch(
            batch_id=batch_id,
            target_state=target_state,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    def detailed_diff(self, previous_batch_id: str, current_batch_id: str) -> dict[str, Any]:
        previous = self.repository.load_diff_ready_batch(previous_batch_id)
        current = self.repository.load_diff_ready_batch(current_batch_id)
        if previous.project_id != current.project_id:
            raise MonitoringBatchRepositoryError(
                "cannot diff batches from different projects"
            )
        detailed = diff_monitoring_batches(
            (row.to_dict() for row in previous.rows),
            (row.to_dict() for row in current.rows),
            previous_mapping_revision=previous.mapping_revision or "",
            current_mapping_revision=current.mapping_revision or "",
            expected_domains=set(current.expected_domains),
            full_snapshot_proven=bool(
                getattr(previous, "full_snapshot_proven", False)
                and getattr(current, "full_snapshot_proven", False)
            ),
            previous_schema_fields=previous.schema_fields,
            current_schema_fields=current.schema_fields,
        )
        return {
            "previous_batch_id": previous_batch_id,
            "current_batch_id": current_batch_id,
            "row_diff": asdict(detailed.row_diff),
            "field_changes": [asdict(change) for change in detailed.field_changes],
            "schema_diffs": [asdict(change) for change in detailed.schema_diffs],
            "identity_match_counts": dict(detailed.identity_match_counts),
            "identity_match_samples": [
                asdict(match) for match in detailed.identity_match_samples
            ],
            "removal_eligible_keys": detailed.removal_eligible_keys,
            "removal_blocked_keys": detailed.removal_blocked_keys,
            "full_snapshot_proven": detailed.full_snapshot_proven,
            "algorithm_version": detailed.algorithm_version,
            "output_sha256": detailed.output_sha256,
        }
