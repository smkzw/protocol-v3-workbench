from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from packages.contracts.workbench_contracts import (
    MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
    MedicalWritingLegacyAuthoringBootstrapPrepareRequest,
    MedicalWritingLegacyAuthoringBootstrapStatus,
)


class MedicalWritingLegacyAuthoringMigrationService:
    """Source-preserving bootstrap for imported protocol/synopsis projects."""

    def __init__(
        self,
        *,
        document_service: Any,
        authoring_journey_service: Any,
        synopsis_import_service: Any,
        project_metadata_resolver: Callable[[str], Any] | None = None,
        runtime_store: Any = None,
    ):
        self.document_service = document_service
        self.authoring_journey_service = authoring_journey_service
        self.synopsis_import_service = synopsis_import_service
        self.project_metadata_resolver = project_metadata_resolver
        self.runtime_store = runtime_store

    def status(
        self, project_id: str, *, import_idempotency_key: str = ""
    ) -> MedicalWritingLegacyAuthoringBootstrapStatus:
        document, source_path, source_sha256, source_role = self._source(project_id)
        if self.authoring_journey_service.has_project(project_id):
            journey = self.authoring_journey_service.get(project_id)
            definition = journey.study_definition
            confirmed_source_role = self._confirmed_source_role(definition)
            sidecar = (
                self.runtime_store.medical_writing_document_binding_sidecar(
                    project_id, document.document_id
                )
                if self.runtime_store is not None
                else None
            )
            bound = bool(
                definition
                and (
                    (
                        document.source_study_definition_id
                        == definition.definition_id
                        and document.source_study_definition_revision
                        == definition.revision
                        and document.source_study_definition_sha256
                        == definition.state_sha256
                    )
                    or (
                        sidecar
                        and sidecar["definition_id"] == definition.definition_id
                        and sidecar["definition_revision"] == definition.revision
                        and sidecar["definition_sha256"] == definition.state_sha256
                    )
                )
            )
            return MedicalWritingLegacyAuthoringBootstrapStatus(
                project_id=project_id,
                state="bound" if bound else "confirmed_ready_for_binding",
                document_id=document.document_id,
                source_filename=source_path.name,
                source_sha256=source_sha256,
                source_role=source_role,
                detected_source_role=source_role,
                confirmed_source_role=confirmed_source_role,
                study_definition_id=definition.definition_id if definition else "",
                study_definition_revision=definition.revision if definition else None,
                study_definition_sha256=definition.state_sha256 if definition else "",
                next_action="" if bound else "bind_imported_document",
                message=(
                    "旧导入来源已形成经确认的StudyDefinition。"
                    if definition
                    else "当前作者旅程尚未形成StudyDefinition。"
                ),
            )
        if not import_idempotency_key:
            latest_job = getattr(
                self.synopsis_import_service,
                "latest_job_for_source",
                None,
            )
            if callable(latest_job):
                import_idempotency_key = latest_job(
                    project_id,
                    source_sha256,
                )
        if not import_idempotency_key:
            return MedicalWritingLegacyAuthoringBootstrapStatus(
                project_id=project_id,
                state="eligible",
                document_id=document.document_id,
                source_filename=source_path.name,
                source_sha256=source_sha256,
                source_role=source_role,
                detected_source_role=source_role,
                next_action="start_source_extraction",
                message="原始文件保持只读；提取候选经医学经理确认后才创建StudyDefinition。",
            )
        job = self.synopsis_import_service.get_job(
            project_id, import_idempotency_key
        )
        if job.status == "review_ready":
            candidate = self.synopsis_import_service.get_job_result(
                project_id, import_idempotency_key
            )
            state = "review_pending"
        elif job.status in {"failed", "cancelled"}:
            candidate = None
            state = "failed"
        else:
            candidate = None
            state = "extracting"
        return MedicalWritingLegacyAuthoringBootstrapStatus(
            project_id=project_id,
            state=state,
            document_id=document.document_id,
            source_filename=source_path.name,
            source_sha256=source_sha256,
            source_role=source_role,
            detected_source_role=source_role,
            import_idempotency_key=import_idempotency_key,
            job_id=job.job_id,
            job_status=job.status,
            warnings=list(job.warnings),
            candidate=candidate,
            next_action=(
                "confirm_extracted_study_definition"
                if state == "review_pending"
                else ""
            ),
            message=job.error_message if state == "failed" else "",
        )

    def prepare(
        self,
        project_id: str,
        request: MedicalWritingLegacyAuthoringBootstrapPrepareRequest,
    ) -> MedicalWritingLegacyAuthoringBootstrapStatus:
        if self.authoring_journey_service.has_project(project_id):
            raise ValueError("legacy bootstrap is only available before a journey exists")
        document, source_path, source_sha256, source_role = self._source(project_id)
        self._require_source_identity(
            document.document_id,
            source_sha256,
            request.expected_document_id,
            request.expected_source_sha256,
        )
        metadata = (
            self.project_metadata_resolver(project_id)
            if self.project_metadata_resolver is not None
            else None
        )
        expected_indication = request.expected_indication or str(
            getattr(metadata, "indication", "") or ""
        )
        media_type = (
            "application/pdf"
            if source_path.suffix.lower() == ".pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        started = self.synopsis_import_service.start_job(
            project_id,
            filename=source_path.name,
            content_type=media_type,
            payload=source_path.read_bytes(),
            expected_indication=expected_indication,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )
        return MedicalWritingLegacyAuthoringBootstrapStatus(
            project_id=project_id,
            state="extracting",
            document_id=document.document_id,
            source_filename=source_path.name,
            source_sha256=source_sha256,
            source_role=source_role,
            detected_source_role=source_role,
            import_idempotency_key=started.idempotency_key,
            job_id=started.job_id,
            job_status=started.status,
            warnings=list(started.warnings),
            next_action="poll_source_extraction",
        )

    def confirm(
        self,
        project_id: str,
        request: MedicalWritingLegacyAuthoringBootstrapConfirmRequest,
    ) -> MedicalWritingLegacyAuthoringBootstrapStatus:
        document, source_path, source_sha256, source_role = self._source(project_id)
        self._require_source_identity(
            document.document_id,
            source_sha256,
            request.expected_document_id,
            request.expected_source_sha256,
        )
        imported = self.synopsis_import_service.get_job_result(
            project_id, request.import_idempotency_key
        )
        if (
            imported.source is None
            or imported.source.source_id != request.source_id
            or imported.source.content_sha256 != source_sha256
        ):
            raise ValueError("source file changed after extraction or source identity is stale")
        confirmed_source_role = request.confirmed_source_role
        if confirmed_source_role is None:
            raise ValueError(
                "confirmed_source_role is required for explicit medical-author confirmation"
            )
        if (
            confirmed_source_role != source_role
            and len(request.source_role_override_reason) < 10
        ):
            raise ValueError(
                "a substantive source-role override reason of at least 10 characters is required"
            )
        journey = self.authoring_journey_service.bootstrap_confirmed_legacy_import(
            project_id,
            imported,
            request,
            source_origin=(
                "full_protocol_import"
                if confirmed_source_role == "protocol"
                else "synopsis_import"
            ),
        )
        definition = journey.study_definition
        if definition is None:
            raise RuntimeError("legacy bootstrap did not create a StudyDefinition")
        return MedicalWritingLegacyAuthoringBootstrapStatus(
            project_id=project_id,
            state="confirmed_ready_for_binding",
            document_id=document.document_id,
            source_filename=source_path.name,
            source_sha256=source_sha256,
            source_role=source_role,
            detected_source_role=source_role,
            confirmed_source_role=confirmed_source_role,
            import_idempotency_key=request.import_idempotency_key,
            candidate=journey.synopsis_import,
            study_definition_id=definition.definition_id,
            study_definition_revision=definition.revision,
            study_definition_sha256=definition.state_sha256,
            next_action="bind_imported_document",
            message="医学确认已完成；原始文件保持只读，可进入既有文档绑定流程。",
        )

    def _source(self, project_id: str):
        if self.document_service.source_mode(project_id) != "original_protocol_docx":
            raise ValueError("project is not a legacy imported protocol/synopsis")
        document = self.document_service.document_for_revision(project_id)
        source_path = Path(self.document_service.original_protocol_path(project_id))
        payload = source_path.read_bytes()
        source_sha256 = hashlib.sha256(payload).hexdigest()
        source_role = "protocol" if len(document.sections) > 3 else "synopsis"
        return document, source_path, source_sha256, source_role

    @staticmethod
    def _confirmed_source_role(definition: Any) -> str | None:
        if definition is None:
            return None
        if definition.origin == "full_protocol_import":
            return "protocol"
        if definition.origin in {"imported_synopsis", "synopsis_import"}:
            return "synopsis"
        return None

    @staticmethod
    def _require_source_identity(
        document_id: str,
        source_sha256: str,
        expected_document_id: str,
        expected_source_sha256: str,
    ) -> None:
        if document_id != expected_document_id:
            raise ValueError("source document changed; refresh the migration preview")
        if source_sha256 != expected_source_sha256:
            raise ValueError("source file changed; refresh the migration preview")
