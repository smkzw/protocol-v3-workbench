from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from .eligibility_artifact_store import (
    EligibilityArtifactMetadata,
    EligibilityArtifactStore,
)
from .sqlite_runtime_store import SqliteRuntimeStore, TENANT_PLACEHOLDER


_MAX_REVIEW_TEXT_CHARACTERS = 100_000


class EligibilityVisualQcPacketError(ValueError):
    pass


@dataclass(frozen=True)
class EligibilityVisualQcImage:
    body: bytes
    media_type: str


class EligibilityVisualQcService:
    def __init__(
        self,
        store: SqliteRuntimeStore,
        artifact_store: EligibilityArtifactStore,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store

    def queue(
        self,
        project_id: str,
        subject_id: str,
        *,
        offset: int,
        limit: int,
        result_filter: str = "all",
    ) -> Dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("visual QC pagination is invalid")
        allowed_filters = {
            "all",
            "pending",
            "sampled_pass",
            "sampled_fail",
            "manual_review_required",
        }
        if result_filter not in allowed_filters:
            raise ValueError("visual QC result filter is invalid")
        with self.store._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.evidence_id, e.source_id, e.source_revision,
                       e.extraction_revision, e.locator_json, e.metadata_json,
                       e.media_class, e.created_at,
                       COALESCE(q.qc_revision, 0) AS qc_revision,
                       q.effective_result AS qc_result,
                       q.reason_code AS qc_reason_code
                FROM eligibility_evidence_spans e
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                 AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                 AND s.source_revision=e.source_revision
                LEFT JOIN eligibility_evidence_visual_qc_state q
                  ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
                 AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
                 AND q.source_revision=e.source_revision
                 AND q.extraction_revision=e.extraction_revision
                WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                  AND s.is_current = 1
                ORDER BY e.source_id, e.evidence_id
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id),
            ).fetchall()
        status_counts = {
            "pending": 0,
            "sampled_pass": 0,
            "sampled_fail": 0,
            "manual_review_required": 0,
        }
        for row in rows:
            status = str(row["qc_result"] or "pending")
            if status not in status_counts:
                raise EligibilityVisualQcPacketError(
                    "visual QC state contains an unsupported result"
                )
            status_counts[status] += 1
        filtered = (
            rows
            if result_filter == "all"
            else [
                row
                for row in rows
                if str(row["qc_result"] or "pending") == result_filter
            ]
        )
        total = len(filtered)
        selected = filtered[offset : offset + limit]
        return {
            "project_id": project_id,
            "subject_id": subject_id,
            "offset": offset,
            "limit": limit,
            "total": total,
            "overall_total": len(rows),
            "result_filter": result_filter,
            "status_counts": status_counts,
            "items": [
                self._packet_item(project_id, subject_id, dict(row))
                for row in selected
            ],
        }

    def image(
        self,
        project_id: str,
        subject_id: str,
        artifact_id: str,
    ) -> EligibilityVisualQcImage:
        with self.store._connect() as connection:
            row = connection.execute(
                """
                SELECT a.storage_key, a.content_hash, a.size_bytes,
                       a.media_type, a.artifact_kind
                FROM eligibility_evidence_artifacts a
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=a.tenant_id AND s.project_id=a.project_id
                 AND s.subject_id=a.subject_id AND s.source_id=a.source_id
                 AND s.source_revision=a.source_revision
                WHERE a.tenant_id = ? AND a.project_id = ? AND a.subject_id = ?
                  AND a.artifact_id = ? AND s.is_current = 1
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    artifact_id,
                ),
            ).fetchone()
        if row is None or str(row["artifact_kind"]) not in {
            "pdf_page_image",
            "ocr_input_image",
        }:
            raise KeyError(artifact_id)
        media_type = str(row["media_type"])
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise EligibilityVisualQcPacketError(
                "visual QC image type is not browser-reviewable"
            )
        body = self.artifact_store.read(
            EligibilityArtifactMetadata(
                storage_key=str(row["storage_key"]),
                content_hash=str(row["content_hash"]),
                size_bytes=int(row["size_bytes"]),
                media_type=media_type,
            )
        )
        return EligibilityVisualQcImage(body=body, media_type=media_type)

    def reconcile_processing_unit(
        self,
        project_id: str,
        subject_id: str,
        evidence_id: str,
        *,
        qc_idempotency_key: str,
        actor: str,
    ) -> Dict[str, Any]:
        with self.store._connect() as connection:
            anchor = connection.execute(
                """
                SELECT e.source_id, e.source_revision, e.locator_json,
                       s.subject_source_revision, s.processing_unit_kind
                FROM eligibility_evidence_spans e
                JOIN eligibility_source_revisions s
                  ON s.tenant_id=e.tenant_id AND s.project_id=e.project_id
                 AND s.subject_id=e.subject_id AND s.source_id=e.source_id
                 AND s.source_revision=e.source_revision
                WHERE e.tenant_id = ? AND e.project_id = ? AND e.subject_id = ?
                  AND e.evidence_id = ? AND s.is_current = 1
                """,
                (TENANT_PLACEHOLDER, project_id, subject_id, evidence_id),
            ).fetchone()
            if anchor is None:
                raise KeyError(evidence_id)
            locator = json.loads(str(anchor["locator_json"]))
            unit_kind = str(anchor["processing_unit_kind"])
            unit_index = (
                int(locator.get("page") or 0)
                if isinstance(locator, dict) and unit_kind == "page"
                else 1
            )
            if unit_index < 1:
                raise EligibilityVisualQcPacketError(
                    "visual QC evidence does not identify its processing unit"
                )
            if unit_kind == "page":
                rows = connection.execute(
                    """
                    SELECT e.evidence_id, e.extraction_revision, e.metadata_json,
                           q.effective_result
                    FROM eligibility_evidence_spans e
                    LEFT JOIN eligibility_evidence_visual_qc_state q
                      ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
                     AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
                     AND q.source_revision=e.source_revision
                     AND q.extraction_revision=e.extraction_revision
                    WHERE e.tenant_id = ? AND e.project_id = ?
                      AND e.subject_id = ? AND e.source_id = ?
                      AND e.source_revision = ?
                      AND CAST(json_extract(e.locator_json, '$.page') AS INTEGER) = ?
                    ORDER BY e.evidence_id
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        anchor["source_id"],
                        anchor["source_revision"],
                        unit_index,
                    ),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT e.evidence_id, e.extraction_revision, e.metadata_json,
                           q.effective_result
                    FROM eligibility_evidence_spans e
                    LEFT JOIN eligibility_evidence_visual_qc_state q
                      ON q.tenant_id=e.tenant_id AND q.project_id=e.project_id
                     AND q.subject_id=e.subject_id AND q.evidence_id=e.evidence_id
                     AND q.source_revision=e.source_revision
                     AND q.extraction_revision=e.extraction_revision
                    WHERE e.tenant_id = ? AND e.project_id = ?
                      AND e.subject_id = ? AND e.source_id = ?
                      AND e.source_revision = ?
                    ORDER BY e.evidence_id
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        anchor["source_id"],
                        anchor["source_revision"],
                    ),
                ).fetchall()
            current = connection.execute(
                """
                SELECT state_revision
                FROM eligibility_source_processing_unit_state
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND subject_source_revision = ? AND source_id = ?
                  AND source_revision = ? AND unit_index = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    anchor["subject_source_revision"],
                    anchor["source_id"],
                    anchor["source_revision"],
                    unit_index,
                ),
            ).fetchone()
        if not rows:
            raise EligibilityVisualQcPacketError(
                "visual QC processing unit has no evidence"
            )
        all_passed = all(
            str(row["effective_result"] or "") == "sampled_pass"
            for row in rows
        )
        evidence_ids = [str(row["evidence_id"]) for row in rows]
        artifact_ids = set()
        for row in rows:
            metadata = json.loads(str(row["metadata_json"]))
            if not isinstance(metadata, dict):
                raise EligibilityVisualQcPacketError(
                    "visual QC processing-unit evidence metadata is invalid"
                )
            artifact_ids.add(str(metadata.get("artifact_id") or ""))
        extraction_revisions = {
            str(row["extraction_revision"])
            for row in rows
        }
        if all_passed and (
            len(artifact_ids) != 1
            or "" in artifact_ids
            or len(extraction_revisions) != 1
        ):
            raise EligibilityVisualQcPacketError(
                "visual QC processing-unit evidence bindings are inconsistent"
            )
        return self.store.commit_eligibility_source_processing_unit(
            project_id=project_id,
            subject_id=subject_id,
            source_id=str(anchor["source_id"]),
            source_revision=str(anchor["source_revision"]),
            subject_source_revision=str(anchor["subject_source_revision"]),
            unit_index=unit_index,
            expected_state_revision=(int(current["state_revision"]) if current else 0),
            processing_status=(
                "evidence_extracted" if all_passed else "manual_review_required"
            ),
            artifact_id=(next(iter(artifact_ids)) if all_passed else None),
            extraction_revision=(
                next(iter(extraction_revisions)) if all_passed else None
            ),
            evidence_ids=(evidence_ids if all_passed else []),
            reason_code=(
                "all_unit_evidence_visual_qc_passed"
                if all_passed
                else "unit_evidence_requires_visual_review"
            ),
            actor=actor,
            idempotency_key=(
                f"{qc_idempotency_key}:processing-unit:{unit_index}"
            ),
        )

    def _packet_item(
        self,
        project_id: str,
        subject_id: str,
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        locator = json.loads(str(row["locator_json"]))
        metadata = json.loads(str(row["metadata_json"]))
        artifact_id = (
            str(metadata.get("artifact_id") or "")
            if isinstance(metadata, dict)
            else ""
        )
        if not artifact_id:
            raise EligibilityVisualQcPacketError(
                "visual QC evidence has no text artifact binding"
            )
        text_artifact = self._artifact_row(
            project_id,
            subject_id,
            artifact_id,
        )
        if any(
            str(text_artifact[key]) != str(row[key])
            for key in ("source_id", "source_revision", "extraction_revision")
        ):
            raise EligibilityVisualQcPacketError(
                "visual QC text artifact binding is inconsistent"
            )
        text = self._artifact_text(text_artifact)
        image_artifact = self._image_artifact(
            project_id,
            subject_id,
            text_artifact,
            locator,
        )
        return {
            "evidence_id": str(row["evidence_id"]),
            "source_revision": str(row["source_revision"]),
            "extraction_revision": str(row["extraction_revision"]),
            "media_class": str(row["media_class"]),
            "locator": locator,
            "text": text,
            "text_character_count": len(text),
            "image_artifact_id": str(image_artifact["artifact_id"]),
            "image_media_type": str(image_artifact["media_type"]),
            "visual_qc": {
                "qc_revision": int(row["qc_revision"] or 0),
                "result": row["qc_result"],
                "reason_code": row["qc_reason_code"],
            },
        }

    def _artifact_row(
        self,
        project_id: str,
        subject_id: str,
        artifact_id: str,
    ) -> Dict[str, Any]:
        with self.store._connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id, job_id, artifact_kind, storage_key,
                       content_hash, size_bytes, media_type, source_id,
                       source_revision, extraction_revision, locator_json
                FROM eligibility_evidence_artifacts
                WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                  AND artifact_id = ?
                """,
                (
                    TENANT_PLACEHOLDER,
                    project_id,
                    subject_id,
                    artifact_id,
                ),
            ).fetchone()
        if row is None:
            raise EligibilityVisualQcPacketError(
                "visual QC controlled artifact is missing"
            )
        return dict(row)

    def _artifact_text(self, artifact: Dict[str, Any]) -> str:
        if artifact["artifact_kind"] not in {"ocr_text", "pdf_page_text"}:
            raise EligibilityVisualQcPacketError(
                "visual QC text artifact kind is invalid"
            )
        body = self.artifact_store.read(
            EligibilityArtifactMetadata(
                storage_key=str(artifact["storage_key"]),
                content_hash=str(artifact["content_hash"]),
                size_bytes=int(artifact["size_bytes"]),
                media_type=str(artifact["media_type"]),
            )
        )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EligibilityVisualQcPacketError(
                "visual QC text artifact is invalid"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version")
            not in {
                "eligibility_ocr_artifact_v1",
                "eligibility_pdf_text_artifact_v1",
            }
            or payload.get("extraction_revision")
            != artifact["extraction_revision"]
            or not isinstance(payload.get("text"), str)
        ):
            raise EligibilityVisualQcPacketError(
                "visual QC text artifact contract is invalid"
            )
        text = str(payload["text"])
        if len(text) > _MAX_REVIEW_TEXT_CHARACTERS:
            raise EligibilityVisualQcPacketError(
                "visual QC text artifact exceeds the review limit"
            )
        return text

    def _image_artifact(
        self,
        project_id: str,
        subject_id: str,
        text_artifact: Dict[str, Any],
        locator: Dict[str, Any],
    ) -> Dict[str, Any]:
        page = int(locator.get("page") or 0) if isinstance(locator, dict) else 0
        with self.store._connect() as connection:
            if page:
                row = connection.execute(
                    """
                    SELECT artifact_id, media_type
                    FROM eligibility_evidence_artifacts
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND source_id = ? AND source_revision = ?
                      AND artifact_kind = 'pdf_page_image'
                      AND CAST(json_extract(locator_json, '$.page') AS INTEGER) = ?
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        text_artifact["source_id"],
                        text_artifact["source_revision"],
                        page,
                    ),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT artifact_id, media_type
                    FROM eligibility_evidence_artifacts
                    WHERE tenant_id = ? AND project_id = ? AND subject_id = ?
                      AND job_id = ? AND artifact_kind = 'ocr_input_image'
                    """,
                    (
                        TENANT_PLACEHOLDER,
                        project_id,
                        subject_id,
                        text_artifact["job_id"],
                    ),
                ).fetchone()
        if row is None:
            raise EligibilityVisualQcPacketError(
                "visual QC source image artifact is missing"
            )
        return dict(row)
