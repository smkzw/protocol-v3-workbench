"""Durable asynchronous jobs for medical-writing DOCX export.

This module is intentionally route-free.  A future ``main.py`` adapter can
inject the existing synchronous assembly/export functions as callbacks while
reusing the shared medical-writing durable job store and worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from packages.contracts.workbench_contracts import (
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    DurableJobRecord,
    DurableJobStartResponse,
)

from .medical_writing_durable_jobs import (
    DurableJobResult,
    DurableJobStore,
    DurableJobWorker,
)


DOCUMENT_EXPORT_JOB_TYPE = "medical_writing_document_export"
DOCUMENT_EXPORT_ARTIFACT_SCHEMA = "medical_writing_document_export_artifact_v1"
DOCUMENT_EXPORT_STEP_TOTAL = 5
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_SUPPORTED_MODES = frozenset({"draft_preview", "approved_final"})


class MedicalWritingDocumentExportJobError(RuntimeError):
    """Base error for the route-free document export job service."""


class MedicalWritingDocumentExportArtifactUnavailable(
    MedicalWritingDocumentExportJobError
):
    """Raised when a completed, valid artifact is not available for a job."""


@dataclass(frozen=True)
class MedicalWritingDocumentExportJobContext:
    job_id: str
    project_id: str
    mode: str
    payload: Mapping[str, Any]
    input_hash: str
    actor: str


@dataclass(frozen=True)
class MedicalWritingRenderedDocument:
    """Small callback result; DOCX bytes are never persisted in SQLite."""

    content: bytes
    filename: str
    metadata: Mapping[str, Any]
    media_type: str = DOCX_MEDIA_TYPE


@dataclass(frozen=True)
class MedicalWritingDocumentExportArtifact:
    job_id: str
    project_id: str
    path: Path
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class MedicalWritingDocumentExportCallbacks:
    """Adapters around the current synchronous export path.

    Each callback receives only the previous real-stage output.  This keeps the
    durable service independent of ``main.py`` composition details and avoids
    duplicating exporter logic.
    """

    verify_export_conditions: Callable[
        [MedicalWritingDocumentExportJobContext], Any
    ]
    assemble_sections: Callable[
        [MedicalWritingDocumentExportJobContext, Any], Any
    ]
    process_sources_and_citations: Callable[
        [MedicalWritingDocumentExportJobContext, Any], Any
    ]
    render_docx: Callable[
        [MedicalWritingDocumentExportJobContext, Any],
        MedicalWritingRenderedDocument,
    ]


@dataclass(frozen=True)
class _ExportStage:
    phase: str
    label: str
    message: str
    step: int
    percent: float

    def progress(self) -> DurableJobProgressPayload:
        return DurableJobProgressPayload(
            phase=self.phase,
            percent=self.percent,
            step=self.step,
            step_total=DOCUMENT_EXPORT_STEP_TOTAL,
            message=self.message,
        )


_STAGES = (
    _ExportStage(
        "validating_export",
        "核验导出条件",
        "正在核验 DOCX 导出条件",
        1,
        0.05,
    ),
    _ExportStage(
        "assembling_sections",
        "组装章节",
        "正在组装医学写作文档章节",
        2,
        0.25,
    ),
    _ExportStage(
        "processing_sources_and_citations",
        "处理来源/引用",
        "正在处理来源与引用",
        3,
        0.45,
    ),
    _ExportStage(
        "rendering_docx",
        "渲染 DOCX",
        "正在渲染 DOCX 文档",
        4,
        0.65,
    ),
    _ExportStage(
        "hashing_and_packaging",
        "哈希与打包",
        "正在计算哈希并打包 DOCX 产物",
        5,
        0.85,
    ),
)
_COMPLETED_PROGRESS = DurableJobProgressPayload(
    phase="completed",
    percent=1.0,
    step=DOCUMENT_EXPORT_STEP_TOTAL,
    step_total=DOCUMENT_EXPORT_STEP_TOTAL,
    message="DOCX 导出已完成",
)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("document export payload must be JSON serializable") from exc


def _safe_docx_filename(value: str) -> str:
    cleaned = "".join(
        "_"
        if character in {"/", "\\", ":", '"'} or ord(character) < 32
        else character
        for character in str(value or "")
    ).strip(" .")
    if not cleaned.lower().endswith(".docx"):
        cleaned = f"{cleaned}.docx"
    if len(cleaned) > 180:
        cleaned = f"{cleaned[:-5][:175]}.docx"
    return cleaned or "medical-writing.docx"


def _project_scope(project_id: str) -> str:
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:24]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_token = re.sub(r"[^A-Za-z0-9_.-]", "_", token)[:80]
    temporary = path.with_name(f".{path.name}.{safe_token}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class MedicalWritingDocumentExportJobExecutor:
    """Execute the five real DOCX export stages under durable ownership."""

    job_type = DOCUMENT_EXPORT_JOB_TYPE

    def __init__(
        self,
        artifact_root: Path,
        callbacks: MedicalWritingDocumentExportCallbacks,
    ) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.callbacks = callbacks

    @staticmethod
    def _owned(
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
        progress: DurableJobProgressPayload,
    ) -> bool:
        try:
            if cancel_check():
                return False
            return bool(heartbeat(progress))
        except Exception:
            return False

    def execute(
        self,
        job: DurableJobRecord,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[[DurableJobProgressPayload], bool],
    ) -> DurableJobResult:
        stage = _STAGES[0]
        try:
            payload = json.loads(job.payload_json or "{}")
            if not isinstance(payload, dict):
                raise ValueError("durable document export payload must be an object")
            mode = str(payload.get("mode") or "")
            if mode not in _SUPPORTED_MODES:
                raise ValueError(f"unsupported document export mode: {mode!r}")
            request_payload = payload.get("payload") or {}
            if not isinstance(request_payload, dict):
                raise ValueError("document export request payload must be an object")
            context = MedicalWritingDocumentExportJobContext(
                job_id=job.job_id,
                project_id=job.project_id,
                mode=mode,
                payload=request_payload,
                input_hash=job.input_hash,
                actor=job.created_by,
            )

            if not self._owned(cancel_check, heartbeat, stage.progress()):
                return self._ownership_lost(stage)
            verified = self.callbacks.verify_export_conditions(context)

            stage = _STAGES[1]
            if not self._owned(cancel_check, heartbeat, stage.progress()):
                return self._ownership_lost(stage)
            assembled = self.callbacks.assemble_sections(context, verified)

            stage = _STAGES[2]
            if not self._owned(cancel_check, heartbeat, stage.progress()):
                return self._ownership_lost(stage)
            prepared = self.callbacks.process_sources_and_citations(
                context, assembled
            )

            stage = _STAGES[3]
            if not self._owned(cancel_check, heartbeat, stage.progress()):
                return self._ownership_lost(stage)
            rendered = self.callbacks.render_docx(context, prepared)

            stage = _STAGES[4]
            if not self._owned(cancel_check, heartbeat, stage.progress()):
                return self._ownership_lost(stage)
            locator, output_hash = self._package(
                context,
                claim_token,
                rendered,
            )
            if not self._owned(cancel_check, heartbeat, _COMPLETED_PROGRESS):
                return self._ownership_lost(stage)
            return DurableJobResult(
                output_hash=output_hash,
                artifact_locator=locator,
                progress=_COMPLETED_PROGRESS,
            )
        except Exception as exc:
            return DurableJobResult(
                error=(
                    f"DOCX 导出失败（阶段：{stage.label}）: "
                    f"{type(exc).__name__}: {exc}"
                ),
                retryable=False,
            )

    @staticmethod
    def _ownership_lost(stage: _ExportStage) -> DurableJobResult:
        return DurableJobResult(
            error=f"DOCX 导出已取消或失去执行权（阶段：{stage.label}）",
            retryable=False,
        )

    def _package(
        self,
        context: MedicalWritingDocumentExportJobContext,
        claim_token: str,
        rendered: MedicalWritingRenderedDocument,
    ) -> tuple[str, str]:
        if not isinstance(rendered, MedicalWritingRenderedDocument):
            raise TypeError(
                "render_docx must return MedicalWritingRenderedDocument"
            )
        if not isinstance(rendered.content, bytes) or not rendered.content:
            raise ValueError("rendered DOCX content must be non-empty bytes")
        if not rendered.content.startswith(b"PK"):
            raise ValueError("rendered DOCX content is not a ZIP/OOXML package")

        output_hash = hashlib.sha256(rendered.content).hexdigest()
        project_scope = _project_scope(context.project_id)
        job_root = self.artifact_root / project_scope / context.job_id
        artifact_path = job_root / f"document-{output_hash}.docx"
        manifest_path = job_root / f"document-{output_hash}.json"
        filename = _safe_docx_filename(rendered.filename)
        manifest = {
            "schema_version": DOCUMENT_EXPORT_ARTIFACT_SCHEMA,
            "job_id": context.job_id,
            "project_scope": project_scope,
            "mode": context.mode,
            "filename": filename,
            "media_type": rendered.media_type or DOCX_MEDIA_TYPE,
            "sha256": output_hash,
            "size_bytes": len(rendered.content),
            "metadata": dict(rendered.metadata),
        }
        manifest_bytes = _canonical_json(manifest).encode("utf-8")
        token = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()[:16]
        _atomic_write(artifact_path, rendered.content, token)
        _atomic_write(manifest_path, manifest_bytes, token)

        locator = _canonical_json(
            {
                "schema_version": DOCUMENT_EXPORT_ARTIFACT_SCHEMA,
                "project_scope": project_scope,
                "job_id": context.job_id,
                "artifact_relpath": artifact_path.relative_to(
                    self.artifact_root
                ).as_posix(),
                "manifest_relpath": manifest_path.relative_to(
                    self.artifact_root
                ).as_posix(),
                "sha256": output_hash,
                "size_bytes": len(rendered.content),
            }
        )
        return locator, output_hash


class MedicalWritingDocumentExportJobService:
    """Route-free start/status/recovery/artifact facade for DOCX export jobs."""

    def __init__(
        self,
        store: DurableJobStore,
        worker: DurableJobWorker,
        artifact_root: Path,
        callbacks: MedicalWritingDocumentExportCallbacks,
    ) -> None:
        self.store = store
        self.worker = worker
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.executor = MedicalWritingDocumentExportJobExecutor(
            self.artifact_root,
            callbacks,
        )
        self.worker.register_executor(self.executor)

    def start(
        self,
        project_id: str,
        *,
        mode: str,
        idempotency_key: str,
        actor: str,
        payload: Mapping[str, Any] | None = None,
        input_hash: str = "",
        wake: bool = True,
    ) -> DurableJobStartResponse:
        project_id = str(project_id or "").strip()
        idempotency_key = str(idempotency_key or "").strip()
        actor = str(actor or "").strip() or "medical_manager"
        mode = str(mode or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        if mode not in _SUPPORTED_MODES:
            raise ValueError(f"unsupported document export mode: {mode!r}")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")

        request_payload = dict(payload or {})
        envelope = {
            "schema_version": 1,
            "mode": mode,
            "payload": request_payload,
        }
        payload_json = _canonical_json(envelope)
        canonical_input_hash = str(input_hash or "").strip()
        request_hash = hashlib.sha256(
            _canonical_json(
                {
                    "mode": mode,
                    "payload": request_payload,
                    "input_hash": canonical_input_hash,
                }
            ).encode("utf-8")
        ).hexdigest()
        if len(canonical_input_hash) > 128:
            canonical_input_hash = hashlib.sha256(
                canonical_input_hash.encode("utf-8")
            ).hexdigest()
        request = DurableJobCreateRequest(
            project_id=project_id,
            job_type=DOCUMENT_EXPORT_JOB_TYPE,
            business_key=idempotency_key,
            request_hash=request_hash,
            input_hash=canonical_input_hash or request_hash,
            payload_json=payload_json,
            created_by=actor,
            max_attempts=1,
        )
        response = self.store.create_or_reuse(request)
        if wake and response.status not in {"completed", "failed", "cancelled"}:
            self.worker.wake(project_id, response.job_id)
        return response

    def status(self, project_id: str, job_id: str) -> DurableJobRecord:
        return self.store.get(project_id, job_id)

    def wake(self, project_id: str, job_id: str) -> None:
        self.store.get(project_id, job_id)
        self.worker.wake(project_id, job_id)

    def recover(self) -> int:
        return self.worker.recover()

    def read_artifact(
        self,
        project_id: str,
        job_id: str,
    ) -> MedicalWritingDocumentExportArtifact:
        record = self.store.get(project_id, job_id)
        if record.job_type != DOCUMENT_EXPORT_JOB_TYPE:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                f"job is not a document export: {job_id}"
            )
        if record.status != "completed":
            raise MedicalWritingDocumentExportArtifactUnavailable(
                f"document export artifact is not ready: {record.status}"
            )
        try:
            locator = json.loads(record.artifact_locator)
        except (json.JSONDecodeError, TypeError) as exc:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact locator is invalid"
            ) from exc
        if not isinstance(locator, dict):
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact locator is invalid"
            )

        expected_scope = _project_scope(project_id)
        if (
            locator.get("schema_version") != DOCUMENT_EXPORT_ARTIFACT_SCHEMA
            or locator.get("project_scope") != expected_scope
            or locator.get("job_id") != job_id
        ):
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact locator does not match the job scope"
            )
        artifact_path = self._resolve_locator_path(locator, "artifact_relpath")
        manifest_path = self._resolve_locator_path(locator, "manifest_relpath")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact manifest is unavailable"
            ) from exc
        if not isinstance(manifest, dict):
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact manifest is invalid"
            )

        expected_hash = str(locator.get("sha256") or "")
        try:
            expected_size = int(locator.get("size_bytes") or -1)
            manifest_size = int(manifest.get("size_bytes") or -1)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact size metadata is invalid"
            ) from exc
        try:
            actual_size = artifact_path.stat().st_size
            actual_hash = _sha256_path(artifact_path)
        except OSError as exc:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact file is unavailable"
            ) from exc
        if (
            not expected_hash
            or actual_hash != expected_hash
            or actual_hash != record.output_hash
            or actual_size != expected_size
            or manifest.get("schema_version")
            != DOCUMENT_EXPORT_ARTIFACT_SCHEMA
            or manifest.get("sha256") != expected_hash
            or manifest_size != expected_size
            or manifest.get("job_id") != job_id
            or manifest.get("project_scope") != expected_scope
        ):
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact integrity check failed"
            )
        metadata = manifest.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact metadata is invalid"
            )
        return MedicalWritingDocumentExportArtifact(
            job_id=job_id,
            project_id=project_id,
            path=artifact_path,
            filename=str(manifest.get("filename") or "medical-writing.docx"),
            media_type=str(manifest.get("media_type") or DOCX_MEDIA_TYPE),
            sha256=actual_hash,
            size_bytes=actual_size,
            metadata=metadata,
        )

    def _resolve_locator_path(
        self,
        locator: Mapping[str, Any],
        key: str,
    ) -> Path:
        raw = str(locator.get(key) or "")
        if not raw:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                f"document export artifact locator missing {key}"
            )
        candidate = (self.artifact_root / raw).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError as exc:
            raise MedicalWritingDocumentExportArtifactUnavailable(
                "document export artifact path escapes the runtime root"
            ) from exc
        return candidate
