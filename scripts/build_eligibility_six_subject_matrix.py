from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.eligibility import (  # noqa: E402
    RAW_INTAKE_PROJECTS,
    raw_intake_service,
)


FIXED_COHORT = {
    "proj_d001": ("SA07005", "SA17004", "SA11004"),
    "proj_my009_uc": ("S01009", "S08001", "S01008"),
}


def _pdf_page_count(paths: Iterable[Path]) -> tuple[int, List[str]]:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for page-count inspection") from exc

    page_count = 0
    errors: List[str] = []
    for path in paths:
        try:
            with pymupdf.open(path) as document:
                page_count += len(document)
        except Exception as exc:  # A malformed source is a matrix result, not a crash.
            errors.append(type(exc).__name__)
    return page_count, errors


def build_matrix() -> Dict[str, Any]:
    subjects: List[Dict[str, Any]] = []
    for project_id, subject_ids in FIXED_COHORT.items():
        config = RAW_INTAKE_PROJECTS[project_id]
        for subject_id in subject_ids:
            manifest = raw_intake_service.subject_manifest(config, subject_id)
            pdf_paths = [
                raw_intake_service.resolve_subject_source_path(
                    config,
                    subject_id,
                    source.source_id,
                    source.source_revision,
                )
                for source in manifest.sources
                if source.suffix == ".pdf"
            ]
            pdf_pages, pdf_errors = _pdf_page_count(pdf_paths)
            archive_count = int(manifest.source_type_counts.get("archive", 0))
            image_count = int(manifest.source_type_counts.get("image", 0))
            unit_kind_counts: Counter[str] = Counter()
            unit_count_statuses: Counter[str] = Counter()
            expected_processing_unit_count = 0
            for source in manifest.sources:
                unit_kind_counts[source.unit_kind] += source.expected_unit_count
                unit_count_statuses[source.expected_unit_count_status] += 1
                expected_processing_unit_count += source.expected_unit_count
            subjects.append(
                {
                    "project_id": project_id,
                    "subject_id": subject_id,
                    "subject_token": manifest.subject_token,
                    "subject_source_revision": manifest.subject_source_revision,
                    "physical_file_count": manifest.file_count,
                    "logical_source_count": len(manifest.sources),
                    "pdf_page_count": pdf_pages,
                    "standalone_image_count": image_count,
                    "page_or_image_work_units": pdf_pages + image_count,
                    "expected_processing_unit_count": expected_processing_unit_count,
                    "processing_unit_kind_counts": dict(
                        sorted(unit_kind_counts.items())
                    ),
                    "unit_count_statuses": dict(
                        sorted(unit_count_statuses.items())
                    ),
                    "resolved_processing_unit_count": 0,
                    "source_type_counts": manifest.source_type_counts,
                    "pending_visual_fallback_count": (
                        manifest.pending_visual_fallback_count
                    ),
                    "archive_gate": (
                        "blocked_pending_safe_unpack" if archive_count else "not_applicable"
                    ),
                    "pdf_open_error_types": sorted(pdf_errors),
                    "ai_review_gate": "blocked_pending_complete_extraction_and_visual_qc",
                    "unit_ledger_gate": "blocked_no_resolved_units_in_isolated_matrix",
                }
            )
    return {
        "schema_version": "eligibility_six_subject_matrix_v2",
        "source_policy": "original_protocol_and_original_subject_files_only",
        "legacy_conclusions_allowed": False,
        "clinical_image_vlm_authorized": False,
        "subjects": subjects,
        "totals": {
            "project_count": len(FIXED_COHORT),
            "subject_count": len(subjects),
            "physical_file_count": sum(
                row["physical_file_count"] for row in subjects
            ),
            "pdf_page_count": sum(row["pdf_page_count"] for row in subjects),
            "standalone_image_count": sum(
                row["standalone_image_count"] for row in subjects
            ),
            "page_or_image_work_units": sum(
                row["page_or_image_work_units"] for row in subjects
            ),
            "expected_processing_unit_count": sum(
                row["expected_processing_unit_count"] for row in subjects
            ),
            "resolved_processing_unit_count": 0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build_matrix(), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(payload, end="")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
