#!/usr/bin/env python3
"""Recheck persisted mixed-OCR evidence without downloading or running OCR again."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import fitz


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _page_text(document: fitz.Document, physical_page: int) -> str:
    if physical_page < 1 or physical_page > document.page_count:
        return ""
    return document.load_page(physical_page - 1).get_text("text").strip()


def main() -> int:
    args = _parse_args()
    if not os.environ.get("WORKBENCH_RUNTIME_DIR"):
        raise SystemExit("WORKBENCH_RUNTIME_DIR is required")

    from services.api.app.main import (
        RUNTIME_DIR,
        _mixed_ocr_consistency_qc_runner,
        writing_reference_repository,
    )
    from services.api.app.ocr_consistency_qc import run_mixed_ocr_consistency_qc

    artifact_root = RUNTIME_DIR / "writing_reference_artifacts"
    results: list[dict] = []
    for artifact in writing_reference_repository.document_artifacts(args.project_id):
        try:
            revision = writing_reference_repository.latest_extraction_revision(
                args.project_id, artifact.artifact_id
            )
            extraction = writing_reference_repository.extraction_result(
                args.project_id, artifact.artifact_id, revision
            )
        except KeyError:
            continue
        base_qc = dict(extraction.ocr_consistency_qc or {})
        if not base_qc.get("triggered"):
            continue
        models = {page.model for page in extraction.ocr_recovery_pages if page.model}
        if len(models) < 2:
            continue

        relative = writing_reference_repository.artifact_storage_relpath(
            args.project_id, artifact.artifact_id
        )
        source_path = (artifact_root / relative).resolve()
        if artifact_root.resolve() not in source_path.parents or not source_path.is_file():
            raise RuntimeError(f"registered artifact is unavailable: {artifact.artifact_id}")

        source_spans = {
            span.span_id: span
            for span in writing_reference_repository.source_spans(
                args.project_id,
                artifact.artifact_id,
                extraction_revision=revision,
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
                        "native_text": _page_text(document, page.physical_page),
                        "previous_page_text": _page_text(
                            document, page.physical_page - 1
                        ),
                        "next_page_text": _page_text(
                            document, page.physical_page + 1
                        ),
                    }
                )
        finally:
            document.close()

        outcome = run_mixed_ocr_consistency_qc(
            evidence, _mixed_ocr_consistency_qc_runner
        )
        results.append(
            {
                "project_id": args.project_id,
                "artifact_id": artifact.artifact_id,
                "nct_id": artifact.nct_id,
                "filename": artifact.filename,
                "extraction_revision": revision,
                "base_qc_identity_hash": str(base_qc.get("identity_hash") or ""),
                "base_qc_verdict": str(base_qc.get("verdict") or ""),
                "fallback_pages": [
                    page.physical_page
                    for page in extraction.ocr_recovery_pages
                    if page.fell_back
                ],
                "recheck": outcome.audit_payload(),
            }
        )

    payload = {
        "schema_version": "mixed_ocr_persisted_recheck_evidence_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": args.project_id,
        "no_download": True,
        "no_ocr": True,
        "document_count": len(results),
        "documents": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
