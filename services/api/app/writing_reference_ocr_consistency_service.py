from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import fitz

from packages.contracts.workbench_contracts.models import (
    WritingReferenceOcrConsistencyQcRecheck,
)

from .ocr_consistency_qc import run_mixed_ocr_consistency_qc
from .writing_reference_repository import (
    WritingReferenceRepository,
    _payload_hash,
)


class WritingReferenceOcrConsistencyService:
    """Create an independent QC record from already persisted OCR evidence."""

    def __init__(
        self,
        repository: WritingReferenceRepository,
        *,
        artifact_root: Path,
        qc_runner: Callable[[str], Any],
        provider: str = "deepseek_official",
        model: str = "deepseek-v4-flash",
        prompt_version: str = "mixed_ocr_consistency_qc_v2_1",
    ) -> None:
        self.repository = repository
        self.artifact_root = artifact_root
        self.qc_runner = qc_runner
        self.provider = provider
        self.model = model
        self.prompt_version = prompt_version

    @staticmethod
    def _page_text(document: fitz.Document, physical_page: int) -> str:
        if physical_page < 1 or physical_page > document.page_count:
            return ""
        return document.load_page(physical_page - 1).get_text("text").strip()

    def recheck(
        self,
        project_id: str,
        artifact_id: str,
        *,
        idempotency_key: str,
    ) -> WritingReferenceOcrConsistencyQcRecheck | None:
        extraction_revision = self.repository.latest_extraction_revision(
            project_id,
            artifact_id,
        )
        extraction = self.repository.extraction_result(
            project_id,
            artifact_id,
            extraction_revision,
        )
        base_qc = dict(extraction.ocr_consistency_qc or {})
        models = sorted(
            {page.model for page in extraction.ocr_recovery_pages if page.model}
        )
        if not base_qc.get("triggered") or len(models) < 2:
            return None

        relative = self.repository.artifact_storage_relpath(
            project_id,
            artifact_id,
        )
        root = self.artifact_root.resolve()
        source_path = (root / relative).resolve()
        if root not in source_path.parents or not source_path.is_file():
            raise RuntimeError("registered OCR source artifact is unavailable")

        source_spans = {
            span.span_id: span
            for span in self.repository.source_spans(
                project_id,
                artifact_id,
                extraction_revision=extraction_revision,
            )
        }
        document = fitz.open(source_path)
        try:
            evidence = []
            for page in extraction.ocr_recovery_pages:
                span = source_spans.get(page.span_id)
                evidence.append(
                    {
                        "physical_page": page.physical_page,
                        "model": page.model,
                        "text": span.source_text if span is not None else "",
                        "fell_back": page.fell_back,
                        "native_text": self._page_text(
                            document,
                            page.physical_page,
                        ),
                        "previous_page_text": self._page_text(
                            document,
                            page.physical_page - 1,
                        ),
                        "next_page_text": self._page_text(
                            document,
                            page.physical_page + 1,
                        ),
                    }
                )
        finally:
            document.close()

        input_hash = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        outcome = run_mixed_ocr_consistency_qc(evidence, self.qc_runner)
        output_payload = outcome.audit_payload()
        output_hash = hashlib.sha256(
            json.dumps(
                output_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        current = self.repository.latest_ocr_consistency_qc_recheck(
            project_id,
            artifact_id,
            extraction_revision,
        )
        if (
            current is not None
            and current.base_qc_identity_hash
            == str(base_qc.get("identity_hash") or _payload_hash(base_qc))
            and current.stage_version
            == str(output_payload.get("qc_stage_version") or "")
            and current.input_hash == input_hash
            and current.output_hash == output_hash
        ):
            return current

        expected_revision = current.revision if current is not None else 0
        revision = expected_revision + 1
        identity = {
            "project_id": project_id,
            "artifact_id": artifact_id,
            "extraction_revision": extraction_revision,
            "base_qc_identity_hash": str(
                base_qc.get("identity_hash") or _payload_hash(base_qc)
            ),
            "stage_version": str(
                output_payload.get("qc_stage_version")
                or "mixed_ocr_consistency_qc_v2_1"
            ),
            "input_hash": input_hash,
            "output_hash": output_hash,
            "revision": revision,
        }
        recheck = WritingReferenceOcrConsistencyQcRecheck(
            recheck_id="wref_ocr_recheck_" + _payload_hash(identity)[:24],
            project_id=project_id,
            artifact_id=artifact_id,
            extraction_revision=extraction_revision,
            base_qc_identity_hash=identity["base_qc_identity_hash"],
            stage_version=identity["stage_version"],
            schema_version=str(
                output_payload.get("qc_schema_version")
                or "mixed_ocr_consistency_qc_v2"
            ),
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
            models=list(output_payload.get("models") or models),
            physical_pages=sorted(
                {
                    page.physical_page
                    for page in extraction.ocr_recovery_pages
                    if page.fell_back
                }
            ),
            verdict=str(output_payload["verdict"]),
            notes=str(output_payload.get("notes") or ""),
            input_hash=input_hash,
            output_hash=output_hash,
            revision=revision,
            created_at=datetime.now(timezone.utc),
        )
        return self.repository.save_ocr_consistency_qc_recheck(
            recheck,
            expected_revision=expected_revision,
            idempotency_key=(
                f"{idempotency_key}:{extraction_revision}:"
                f"{recheck.stage_version}:{input_hash}"
            ),
        )
