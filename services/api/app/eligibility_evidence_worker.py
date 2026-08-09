from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from .eligibility_artifact_store import (
    ArtifactAlreadyExistsError,
    ArtifactIntegrityError,
    EligibilityArtifactMetadata,
    EligibilityArtifactStore,
)
from .ocr_gateway import (
    LocalOcrGateway,
    OcrGatewayRequestError,
    OcrGatewayRuntimeError,
    OcrRequest,
    OCR_PROFILE_MODELS,
    ocr_profile_digest,
    validate_ocr_profile_model,
)
from .sqlite_runtime_store import SqliteRuntimeStore, StaleRuntimeStateError
from .vlm_gateway import (
    LocalVlmGateway,
    VlmCircuitOpenError,
    VlmGatewayRequestError,
    VlmGatewayRuntimeError,
)


SourceResolver = Callable[[Dict[str, object]], Path]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _opaque_id(prefix: str, *parts: str, length: int = 24) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:length]}"


class EligibilityEvidenceWorker:
    """Executes one durable evidence task without producing a medical decision."""

    def __init__(
        self,
        *,
        store: SqliteRuntimeStore,
        artifact_store: EligibilityArtifactStore,
        source_resolver: SourceResolver,
        ocr_gateway: Optional[LocalOcrGateway] = None,
        vlm_gateway: Optional[LocalVlmGateway] = None,
        profile_version: Optional[str] = None,
        ocr_child_profiles: Iterable[str] = (),
        clock: Clock = _utc_now,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        self.source_resolver = source_resolver
        self.ocr_gateway = ocr_gateway
        self.vlm_gateway = vlm_gateway
        self.profile_version = profile_version
        self.ocr_child_profiles = tuple(
            dict.fromkeys(str(item) for item in ocr_child_profiles)
        )
        self.clock = clock
        for child_profile in self.ocr_child_profiles:
            ocr_profile_digest(child_profile)
        if profile_version == "pdf-render-200dpi-v1" and not self.ocr_child_profiles:
            raise ValueError("PDF render worker requires explicit OCR child profiles")
        if profile_version in OCR_PROFILE_MODELS:
            settings = getattr(ocr_gateway, "settings", None)
            model = getattr(settings, "model", None)
            validate_ocr_profile_model(profile_version, model)
        if self.ocr_child_profiles and profile_version != "pdf-render-200dpi-v1":
            raise ValueError("OCR child profiles are only valid for PDF render workers")
        if vlm_gateway is not None:
            configured_profile = vlm_gateway.settings.profile
            if profile_version != configured_profile.profile_version:
                raise ValueError("VLM worker profile does not match configured gateway")
            if not bool(getattr(vlm_gateway, "uses_durable_circuit", False)):
                raise ValueError("VLM worker requires a durable circuit breaker")

    def run_once(self, worker_id: str) -> Optional[Dict[str, object]]:
        now = self.clock()
        worker_job_kind = None
        expected_profile_digest = None
        if self.profile_version in OCR_PROFILE_MODELS:
            worker_job_kind = "ocr"
        elif self.profile_version == "pdf-text-pymupdf-v1":
            worker_job_kind = "pdf_text_extraction"
        elif self.profile_version == "pdf-render-200dpi-v1":
            worker_job_kind = "pdf_page_render"
        elif self.vlm_gateway is not None:
            worker_job_kind = "vlm"
            expected_profile_digest = self.vlm_gateway.settings.profile.profile_digest
        job = self.store.claim_next_eligibility_evidence_job(
            worker_id,
            now=now,
            lease_seconds=300,
            job_kind=worker_job_kind,
            profile_version=self.profile_version,
            profile_digest=expected_profile_digest,
        )
        if job is None:
            return None
        try:
            if job["job_kind"] == "ocr":
                if self.ocr_gateway is None:
                    raise OcrGatewayRuntimeError("Local OCR gateway is unavailable")
                self._run_ocr(job)
            elif job["job_kind"] == "pdf_text_extraction":
                self._run_pdf_text(job, worker_id)
            elif job["job_kind"] == "pdf_page_render":
                self._run_pdf_render(job, worker_id)
                finalized = self.store.finalize_pdf_render_with_ocr_children(
                    str(job["project_id"]),
                    str(job["job_id"]),
                    worker_id=worker_id,
                    profile_versions=self.ocr_child_profiles,
                    lease_token=str(job["lease_token"]),
                    now=self.clock(),
                )
                return finalized["parent"]
            elif job["job_kind"] == "vlm":
                if self.vlm_gateway is None:
                    return self.store.fail_eligibility_evidence_job(
                        str(job["project_id"]),
                        str(job["job_id"]),
                        worker_id=worker_id,
                        lease_token=str(job["lease_token"]),
                        error_code="vlm_gateway_not_configured",
                        retry_at=None,
                        now=self.clock(),
                    )
                return self._run_vlm(job, worker_id)
            else:
                return self.store.fail_eligibility_evidence_job(
                    str(job["project_id"]),
                    str(job["job_id"]),
                    worker_id=worker_id,
                    lease_token=str(job["lease_token"]),
                    error_code="job_kind_worker_not_implemented",
                    retry_at=None,
                    now=self.clock(),
                )
            return self.store.complete_eligibility_evidence_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                lease_token=str(job["lease_token"]),
                now=self.clock(),
            )
        except StaleRuntimeStateError:
            raise
        except OcrGatewayRequestError:
            return self.store.fail_eligibility_evidence_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                lease_token=str(job["lease_token"]),
                error_code="ocr_source_rejected",
                retry_at=None,
                now=self.clock(),
            )
        except ArtifactIntegrityError:
            if job["job_kind"] == "vlm":
                return self.store.fail_eligibility_vlm_job(
                    str(job["project_id"]),
                    str(job["job_id"]),
                    worker_id=worker_id,
                    gateway_outcome="rejected",
                    error_code="input_artifact_integrity_failure",
                    attempt_number=int(job["attempt_count"]),
                    lease_token=str(job["lease_token"]),
                    retry_at=None,
                    now=self.clock(),
                )
            return self.store.fail_eligibility_evidence_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                lease_token=str(job["lease_token"]),
                error_code="input_artifact_integrity_failure",
                retry_at=None,
                now=self.clock(),
            )
        except OcrGatewayRuntimeError:
            return self.store.fail_eligibility_evidence_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                lease_token=str(job["lease_token"]),
                error_code="ocr_runtime_failure",
                retry_at=self.clock() + timedelta(minutes=1),
                now=self.clock(),
            )
        except VlmGatewayRequestError:
            return self.store.fail_eligibility_vlm_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                gateway_outcome="rejected",
                error_code="vlm_request_rejected",
                attempt_number=int(job["attempt_count"]),
                lease_token=str(job["lease_token"]),
                retry_at=None,
                now=self.clock(),
            )
        except VlmCircuitOpenError as exc:
            return self.store.defer_eligibility_vlm_job_for_circuit(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                attempt_number=int(job["attempt_count"]),
                lease_token=str(job["lease_token"]),
                retry_at=exc.retry_at,
                now=self.clock(),
            )
        except VlmGatewayRuntimeError:
            return self.store.fail_eligibility_vlm_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                gateway_outcome="runtime_failed",
                error_code="vlm_runtime_failure",
                attempt_number=int(job["attempt_count"]),
                lease_token=str(job["lease_token"]),
                retry_at=self.clock() + timedelta(minutes=1),
                now=self.clock(),
            )
        except Exception:
            if job["job_kind"] == "vlm" and job.get("profile_digest"):
                return self.store.fail_eligibility_vlm_job(
                    str(job["project_id"]),
                    str(job["job_id"]),
                    worker_id=worker_id,
                    gateway_outcome="runtime_failed",
                    error_code="vlm_internal_failure",
                    attempt_number=int(job["attempt_count"]),
                    lease_token=str(job["lease_token"]),
                    retry_at=self.clock() + timedelta(minutes=1),
                    now=self.clock(),
                )
            return self.store.fail_eligibility_evidence_job(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                lease_token=str(job["lease_token"]),
                error_code="evidence_worker_internal_failure",
                retry_at=self.clock() + timedelta(minutes=1),
                now=self.clock(),
            )

    def _run_vlm(
        self, job: Dict[str, object], worker_id: str
    ) -> Dict[str, object]:
        if self.vlm_gateway is None:
            raise VlmGatewayRuntimeError("Local VLM gateway is unavailable")
        with self.vlm_gateway.admit() as circuit_call:
            self.store.start_eligibility_vlm_provider_attempt(
                str(job["project_id"]),
                str(job["job_id"]),
                worker_id=worker_id,
                attempt_number=int(job["attempt_count"]),
                lease_token=str(job["lease_token"]),
                now=self.clock(),
            )
            return self._run_vlm_admitted(job, worker_id, circuit_call)

    def _run_vlm_admitted(
        self, job: Dict[str, object], worker_id: str, circuit_call: object
    ) -> Dict[str, object]:
        if self.vlm_gateway is None:
            raise VlmGatewayRuntimeError("Local VLM gateway is unavailable")
        expected_digest = self.vlm_gateway.settings.profile.profile_digest
        binding = self.store.eligibility_vlm_inference_input(
            str(job["project_id"]),
            str(job["job_id"]),
            worker_id=worker_id,
            profile_digest=expected_digest,
            attempt_number=int(job["attempt_count"]),
            lease_token=str(job["lease_token"]),
            now=self.clock(),
        )
        max_bytes = int(self.vlm_gateway.settings.profile.normalization.max_bytes)
        if int(binding["size_bytes"]) > max_bytes:
            raise VlmGatewayRequestError("VLM controlled artifact exceeds byte limit")
        image_bytes = self.artifact_store.read_bytes(
            str(binding["storage_key"]),
            expected_hash=str(binding["content_hash"]),
            expected_size_bytes=int(binding["size_bytes"]),
        )
        result = self.vlm_gateway.run(
            image_bytes=image_bytes,
            mime_type=str(binding["media_type"]),
            expected_profile_digest=expected_digest,
            circuit_call=circuit_call,
        )
        if result.profile_version != job["profile_version"]:
            raise VlmGatewayRequestError("VLM result profile is invalid")
        return self.store.finalize_eligibility_vlm_job(
            str(job["project_id"]),
            str(job["job_id"]),
            worker_id=worker_id,
            descriptor=result.descriptor.model_dump(mode="json"),
            outcome=result.outcome.value,
            profile_digest=result.profile_digest,
            normalized_width=result.normalized_width,
            normalized_height=result.normalized_height,
            duration_ms=result.duration_ms,
            attempt_number=int(job["attempt_count"]),
            lease_token=str(job["lease_token"]),
            now=self.clock(),
        )

    def _run_ocr(self, job: Dict[str, object]) -> None:
        profile_version = str(job["profile_version"])
        expected_digest = ocr_profile_digest(profile_version)
        if job.get("profile_digest") != expected_digest:
            raise OcrGatewayRequestError("OCR job profile digest is invalid")
        settings = getattr(self.ocr_gateway, "settings", None)
        configured_model = getattr(settings, "model", None)
        if configured_model is not None:
            validate_ocr_profile_model(profile_version, configured_model)
        input_artifact_id = job.get("input_artifact_id")
        if input_artifact_id is not None:
            artifact = self.store.eligibility_evidence_artifact(
                str(job["project_id"]), str(input_artifact_id)
            )
            if (
                artifact is None
                or artifact["job_id"] != job.get("parent_job_id")
                or artifact["subject_id"] != job["subject_id"]
                or artifact["source_id"] != job["source_id"]
                or artifact["source_revision"] != job["source_revision"]
                or artifact["artifact_kind"] != "pdf_page_image"
                or artifact["media_type"] != "image/png"
                or artifact["locator"].get("page") != job.get("page_index")
            ):
                raise OcrGatewayRequestError("OCR page artifact identity is invalid")
            image_bytes = self.artifact_store.read_bytes(
                artifact["storage_key"],
                expected_hash=artifact["content_hash"],
                expected_size_bytes=artifact["size_bytes"],
            )
            result = self.ocr_gateway.run(
                OcrRequest(image_bytes=image_bytes, image_suffix=".png")
            )
            if result.content_hash != artifact["content_hash"]:
                raise ArtifactIntegrityError("OCR gateway input hash mismatch")
            locator = {
                "page": int(job["page_index"]),
                "parent_job_id": str(job["parent_job_id"]),
            }
            source_input = None
        else:
            source_path = self.source_resolver(job)
            source_bytes = source_path.read_bytes()
            source_suffix = source_path.suffix.lower()
            result = self.ocr_gateway.run(
                OcrRequest(image_bytes=source_bytes, image_suffix=source_suffix)
            )
            if result.content_hash != hashlib.sha256(source_bytes).hexdigest():
                raise ArtifactIntegrityError("OCR direct input hash mismatch")
            locator = {"source_scope": "whole_image"}
            source_input = (source_bytes, source_suffix)
        if result.model != OCR_PROFILE_MODELS[profile_version]:
            raise OcrGatewayRuntimeError("OCR provider returned the wrong model")
        extraction_revision = _opaque_id(
            "eligextractv",
            str(job["source_revision"]),
            result.model,
            result.content_hash,
        )
        body = _canonical_bytes(
            {
                "schema_version": "eligibility_ocr_artifact_v1",
                "source_token": result.source_token,
                "extraction_revision": extraction_revision,
                "model": result.model,
                "called_at": result.called_at.isoformat(),
                "text": result.text,
            }
        )
        storage_key = "/".join(
            (
                str(job["project_id"]),
                str(job["subject_id"]),
                str(job["job_id"]),
                "ocr-result.json",
            )
        )
        metadata = self._write_or_verify(storage_key, body, "application/json")
        artifact_id = _opaque_id(
            "eligartifact", str(job["job_id"]), metadata.content_hash
        )
        evidence_id = _opaque_id(
            "eligevidence", artifact_id, extraction_revision
        )
        timestamp = str(job["created_at"])
        input_artifact_id = None
        if source_input is not None:
            source_bytes, source_suffix = source_input
            source_media_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".tif": "image/tiff",
                ".tiff": "image/tiff",
            }[source_suffix]
            input_storage_key = "/".join(
                (
                    str(job["project_id"]),
                    str(job["subject_id"]),
                    str(job["job_id"]),
                    f"ocr-input{source_suffix}",
                )
            )
            input_metadata = self._write_or_verify(
                input_storage_key,
                source_bytes,
                source_media_type,
            )
            input_artifact_id = _opaque_id(
                "eligartifactinput",
                str(job["job_id"]),
                input_metadata.content_hash,
            )
            self.store.add_eligibility_evidence_artifact(
                {
                    "project_id": job["project_id"],
                    "subject_id": job["subject_id"],
                    "job_id": job["job_id"],
                    "artifact_id": input_artifact_id,
                    "artifact_kind": "ocr_input_image",
                    "storage_key": input_metadata.storage_key,
                    "content_hash": input_metadata.content_hash,
                    "size_bytes": input_metadata.size_bytes,
                    "media_type": input_metadata.media_type,
                    "source_id": job["source_id"],
                    "source_revision": job["source_revision"],
                    "extraction_revision": extraction_revision,
                    "locator": locator,
                    "quality_state": "needs_visual_qc",
                    "created_at": timestamp,
                }
            )
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": job["project_id"],
                "subject_id": job["subject_id"],
                "job_id": job["job_id"],
                "artifact_id": artifact_id,
                "artifact_kind": "ocr_text",
                "storage_key": metadata.storage_key,
                "content_hash": metadata.content_hash,
                "size_bytes": metadata.size_bytes,
                "media_type": metadata.media_type,
                "source_id": job["source_id"],
                "source_revision": job["source_revision"],
                "extraction_revision": extraction_revision,
                "locator": locator,
                "quality_state": "needs_visual_qc",
                "created_at": timestamp,
            }
        )
        self.store.add_eligibility_evidence_span(
            {
                "project_id": job["project_id"],
                "subject_id": job["subject_id"],
                "evidence_id": evidence_id,
                "source_id": job["source_id"],
                "source_revision": job["source_revision"],
                "extraction_revision": extraction_revision,
                "locator": locator,
                "metadata": {
                    "artifact_id": artifact_id,
                    "input_artifact_id": input_artifact_id,
                    "character_count": result.character_count,
                    "source_token": result.source_token,
                },
                "media_class": "text_document_image",
                "processing_state": "needs_visual_qc",
                "quality_state": "needs_visual_qc",
                "extraction_confidence": None,
                "medical_verification_status": "not_reviewed",
                "created_at": timestamp,
            }
        )

    def _run_pdf_text(self, job: Dict[str, object], worker_id: str) -> None:
        if job["profile_version"] != "pdf-text-pymupdf-v1":
            raise ValueError("unsupported PDF text extraction profile")
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError("PDF extraction engine unavailable") from exc
        source_path = self.source_resolver(job)
        timestamp = str(job["created_at"])
        with pymupdf.open(source_path) as document:
            total = len(document)
            for page_index, page in enumerate(document):
                text = (page.get_text("text") or "").strip()
                character_count = len("".join(text.split()))
                extraction_revision = _opaque_id(
                    "eligextractv",
                    str(job["source_revision"]),
                    str(job["profile_version"]),
                    str(page_index + 1),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                body = _canonical_bytes(
                    {
                        "schema_version": "eligibility_pdf_text_artifact_v1",
                        "extraction_revision": extraction_revision,
                        "page": page_index + 1,
                        "character_count": character_count,
                        "requires_ocr": character_count < 40,
                        "text": text,
                    }
                )
                storage_key = "/".join((
                    str(job["project_id"]), str(job["subject_id"]),
                    str(job["job_id"]), f"page-{page_index + 1:04d}-text.json",
                ))
                metadata = self._write_or_verify(
                    storage_key, body, "application/json"
                )
                artifact_id = _opaque_id(
                    "eligartifact", str(job["job_id"]), metadata.content_hash
                )
                quality_state = (
                    "needs_visual_qc" if character_count >= 40
                    else "manual_review_required"
                )
                self.store.add_eligibility_evidence_artifact(
                    {
                        "project_id": job["project_id"],
                        "subject_id": job["subject_id"],
                        "job_id": job["job_id"],
                        "artifact_id": artifact_id,
                        "artifact_kind": "pdf_page_text",
                        "storage_key": metadata.storage_key,
                        "content_hash": metadata.content_hash,
                        "size_bytes": metadata.size_bytes,
                        "media_type": metadata.media_type,
                        "source_id": job["source_id"],
                        "source_revision": job["source_revision"],
                        "extraction_revision": extraction_revision,
                        "locator": {"page": page_index + 1},
                        "quality_state": quality_state,
                        "created_at": timestamp,
                    }
                )
                if character_count >= 40:
                    evidence_id = _opaque_id(
                        "eligevidence", artifact_id, extraction_revision
                    )
                    self.store.add_eligibility_evidence_span(
                        {
                            "project_id": job["project_id"],
                            "subject_id": job["subject_id"],
                            "evidence_id": evidence_id,
                            "source_id": job["source_id"],
                            "source_revision": job["source_revision"],
                            "extraction_revision": extraction_revision,
                            "locator": {"page": page_index + 1},
                            "metadata": {
                                "artifact_id": artifact_id,
                                "character_count": character_count,
                            },
                            "media_class": "pdf_text_page",
                            "processing_state": "needs_visual_qc",
                            "quality_state": "needs_visual_qc",
                            "extraction_confidence": None,
                            "medical_verification_status": "not_reviewed",
                            "created_at": timestamp,
                        }
                    )
                self.store.heartbeat_eligibility_evidence_job(
                    str(job["project_id"]), str(job["job_id"]),
                    worker_id=worker_id, progress_current=page_index + 1,
                    progress_total=total,
                    lease_token=str(job["lease_token"]),
                    now=self.clock(), lease_seconds=300,
                )

    def _run_pdf_render(self, job: Dict[str, object], worker_id: str) -> None:
        if job["profile_version"] != "pdf-render-200dpi-v1":
            raise ValueError("unsupported PDF render profile")
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError("PDF rendering engine unavailable") from exc
        source_path = self.source_resolver(job)
        timestamp = str(job["created_at"])
        with pymupdf.open(source_path) as document:
            total = len(document)
            for page_index, page in enumerate(document):
                pixmap = page.get_pixmap(
                    dpi=200,
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                    annots=True,
                )
                body = pixmap.tobytes("png")
                extraction_revision = _opaque_id(
                    "eligextractv",
                    str(job["source_revision"]),
                    str(job["profile_version"]),
                    str(page_index + 1),
                    hashlib.sha256(body).hexdigest(),
                )
                storage_key = "/".join((
                    str(job["project_id"]), str(job["subject_id"]),
                    str(job["job_id"]), f"page-{page_index + 1:04d}.png",
                ))
                metadata = self._write_or_verify(storage_key, body, "image/png")
                artifact_id = _opaque_id(
                    "eligartifact", str(job["job_id"]), metadata.content_hash
                )
                self.store.add_eligibility_evidence_artifact(
                    {
                        "project_id": job["project_id"],
                        "subject_id": job["subject_id"],
                        "job_id": job["job_id"],
                        "artifact_id": artifact_id,
                        "artifact_kind": "pdf_page_image",
                        "storage_key": metadata.storage_key,
                        "content_hash": metadata.content_hash,
                        "size_bytes": metadata.size_bytes,
                        "media_type": metadata.media_type,
                        "source_id": job["source_id"],
                        "source_revision": job["source_revision"],
                        "extraction_revision": extraction_revision,
                        "locator": {"page": page_index + 1, "dpi": 200},
                        "quality_state": "needs_visual_qc",
                        "created_at": timestamp,
                    }
                )
                self.store.heartbeat_eligibility_evidence_job(
                    str(job["project_id"]), str(job["job_id"]),
                    worker_id=worker_id, progress_current=page_index + 1,
                    progress_total=total,
                    lease_token=str(job["lease_token"]),
                    now=self.clock(), lease_seconds=300,
                )

    def _write_or_verify(
        self, storage_key: str, body: bytes, media_type: str
    ) -> EligibilityArtifactMetadata:
        content_hash = hashlib.sha256(body).hexdigest()
        expected = EligibilityArtifactMetadata(
            storage_key=storage_key,
            content_hash=content_hash,
            size_bytes=len(body),
            media_type=media_type,
        )
        try:
            return self.artifact_store.write(storage_key, body, media_type)
        except ArtifactAlreadyExistsError:
            existing = self.artifact_store.read(expected)
            if existing != body:
                raise OcrGatewayRuntimeError("Stored OCR artifact integrity failed")
            return expected
