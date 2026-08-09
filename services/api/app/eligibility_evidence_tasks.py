from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from .ocr_gateway import ocr_profile_digest
from .sqlite_runtime_store import SqliteRuntimeStore


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(prefix: str, value: Any, length: int = 20) -> str:
    payload = f"{prefix}|{_canonical_json(value)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


@dataclass(frozen=True)
class EvidenceSourceIdentity:
    source_id: str
    source_revision: str
    media_class: str


class EligibilityEvidenceTaskService:
    """Durable orchestration metadata; workers and clinical inference stay separate."""

    def __init__(self, store: SqliteRuntimeStore):
        self.store = store

    def create_job(
        self,
        *,
        project_id: str,
        subject_id: str,
        subject_source_revision: str,
        sources: Iterable[EvidenceSourceIdentity],
        source_id: str,
        job_kind: str,
        profile_version: str,
        idempotency_key: str,
        priority: int,
        max_attempts: int,
    ) -> Dict[str, Any]:
        source_by_id = {source.source_id: source for source in sources}
        source = source_by_id.get(source_id)
        if source is None:
            raise KeyError("eligibility evidence source is not current")
        allowed_kinds = self.allowed_job_kinds(source.media_class)
        if job_kind not in allowed_kinds:
            raise ValueError(
                f"{job_kind} is not allowed for current source media class"
            )
        allowed_profiles = {
            "media_classification": {"media-classification-v1"},
            "pdf_text_extraction": {"pdf-text-pymupdf-v1"},
            "pdf_page_render": {"pdf-render-200dpi-v1"},
            "ocr": {"ocr-glm-v1", "ocr-paddle-v1"},
            # VLM creation is intentionally unavailable on the raw-source API.
            # It requires a server-owned controlled-artifact binding.
            "vlm": set(),
        }
        if profile_version not in allowed_profiles[job_kind]:
            raise ValueError("profile_version is not allowed for evidence job kind")
        cache_payload = {
            "project_id": project_id,
            "subject_id": subject_id,
            "source_id": source.source_id,
            "source_revision": source.source_revision,
            "subject_source_revision": subject_source_revision,
            "job_kind": job_kind,
            "profile_version": profile_version,
        }
        cache_key = f"eligcache_{_digest('eligibility-evidence-cache-v1', cache_payload, 32)}"
        job_id = f"eligjob_{_digest('eligibility-evidence-job-v1', cache_payload)}"
        request_payload = {
            **cache_payload,
            "idempotency_key": idempotency_key,
            "priority": priority,
            "max_attempts": max_attempts,
        }
        result = self.store.create_eligibility_evidence_job(
            {
                "project_id": project_id,
                "subject_id": subject_id,
                "job_id": job_id,
                "job_kind": job_kind,
                "profile_version": profile_version,
                "source_id": source.source_id,
                "source_revision": source.source_revision,
                "subject_source_revision": subject_source_revision,
                "cache_key": cache_key,
                "priority": priority,
                "max_attempts": max_attempts,
                "profile_digest": (
                    ocr_profile_digest(profile_version)
                    if job_kind == "ocr"
                    else None
                ),
            },
            idempotency_key=idempotency_key,
            request_fingerprint=_digest(
                "eligibility-evidence-request-v1", request_payload, 64
            ),
        )
        return {"job": self.public_job(result["job"]), "replayed": result["replayed"]}

    def expand_pdf_render_to_ocr(
        self,
        *,
        project_id: str,
        parent_job_id: str,
        profile_version: str,
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 3,
    ) -> List[Dict[str, Any]]:
        if profile_version not in {"ocr-glm-v1", "ocr-paddle-v1"}:
            raise ValueError("profile_version is not allowed for PDF page OCR")
        parent = self.store.eligibility_evidence_job(project_id, parent_job_id)
        if (
            parent is None
            or parent["status"] != "succeeded"
            or parent["job_kind"] != "pdf_page_render"
            or parent["profile_version"] != "pdf-render-200dpi-v1"
        ):
            raise ValueError("completed PDF render parent job is required")
        children = self.store.eligibility_pdf_render_ocr_children(
            project_id, parent_job_id, profile_versions=(profile_version,)
        )
        if not children:
            raise ValueError("PDF render parent has no atomically finalized OCR children")
        expected_pages = set(range(1, int(parent["progress_total"]) + 1))
        if (
            not expected_pages
            or len(children) != len(expected_pages)
            or {child["page_index"] for child in children} != expected_pages
            or any(
                child["profile_digest"] != ocr_profile_digest(profile_version)
                or child["parent_job_id"] != parent_job_id
                for child in children
            )
        ):
            raise RuntimeError(
                "PDF render OCR child batch is incomplete or has a legacy profile"
            )
        return [
            {"job": self.public_job(child), "replayed": True}
            for child in children
        ]

    @staticmethod
    def allowed_job_kinds(media_class: str) -> set[str]:
        if media_class == "pdf":
            return {"pdf_text_extraction", "pdf_page_render", "media_classification"}
        if media_class == "image":
            return {"media_classification", "ocr", "vlm"}
        if media_class in {"doc", "docx"}:
            return {"media_classification"}
        return {"media_classification"}

    @staticmethod
    def public_job(job: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "project_id", "subject_id", "job_id", "job_kind", "profile_version", "source_id",
            "source_revision", "subject_source_revision", "status", "priority",
            "attempt_count", "max_attempts", "progress_current", "progress_total",
            "error_code", "next_run_at", "created_at", "updated_at", "completed_at",
            "parent_job_id", "page_index",
        }
        return {key: job.get(key) for key in allowed}

    def jobs_for_subject(self, project_id: str, subject_id: str) -> List[Dict[str, Any]]:
        return [
            self.public_job(job)
            for job in self.store.eligibility_subject_evidence_jobs(project_id, subject_id)
        ]

    def cancel_job(
        self, project_id: str, job_id: str, *, actor: str
    ) -> Dict[str, Any]:
        return self.public_job(
            self.store.cancel_eligibility_evidence_job(
                project_id, job_id, actor=actor
            )
        )

    def public_artifacts(self, project_id: str, job_id: str) -> List[Dict[str, Any]]:
        return [
            {
                key: artifact[key]
                for key in (
                    "project_id", "subject_id", "job_id", "artifact_id",
                    "artifact_kind", "size_bytes", "media_type", "source_id",
                    "source_revision", "extraction_revision", "locator",
                    "quality_state", "created_at",
                )
            }
            for artifact in self.store.eligibility_evidence_artifacts(project_id, job_id)
        ]
