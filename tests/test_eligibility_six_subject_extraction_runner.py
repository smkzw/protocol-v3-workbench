from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.run_eligibility_six_subject_extraction import (
    ACTIVE_RUNTIME_DIR,
    FIXED_COHORT,
    RAW_INTAKE_PROJECTS,
    bounded_limit,
    dry_run_summary,
    parse_stages,
    planned_counts,
    seed_jobs,
    validate_isolated_paths,
    validate_ocr_configuration,
    validate_runtime_scope,
    verify_artifact_integrity,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


def source(source_type: str, expected_unit_count: int = 1):
    return SimpleNamespace(
        source_type=source_type,
        expected_unit_count=expected_unit_count,
    )


class SixSubjectExtractionRunnerTests(unittest.TestCase):
    def test_plan_counts_pdf_children_images_and_blocked_sources(self) -> None:
        manifests = {
            "project-a": [
                SimpleNamespace(
                    sources=[
                        source("pdf", 3),
                        source("image"),
                        source("doc"),
                        source("archive"),
                    ]
                )
            ]
        }
        self.assertEqual(
            {
                "blocked_archive_sources": 1,
                "blocked_document_sources": 1,
                "direct_image_ocr": 1,
                "expected_ocr_calls": 4,
                "expected_pdf_ocr_children": 3,
                "pdf_page_render": 1,
                "pdf_text_extraction": 1,
            },
            planned_counts(manifests),
        )

    def test_dry_run_summary_has_no_identifiers_paths_or_content(self) -> None:
        payload = dry_run_summary(
            {"project-a": [SimpleNamespace(sources=[source("pdf", 2)])]}
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in (
            "subject_id",
            "subject_token",
            "source_id",
            "job_id",
            "storage_key",
            "filename",
            "text_preview",
            "/Users/",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(payload["contains_medical_decisions"])
        self.assertFalse(payload["visual_qc_automatically_passed"])
        self.assertFalse(payload["vlm_jobs_allowed"])

    def test_active_and_source_overlapping_paths_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "active runtime"):
            validate_isolated_paths(
                ACTIVE_RUNTIME_DIR,
                ACTIVE_RUNTIME_DIR / "artifacts",
            )
        first_project = next(iter(FIXED_COHORT))
        source_root = Path(RAW_INTAKE_PROJECTS[first_project].raw_subject_root)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "isolated from sources"):
                validate_isolated_paths(Path(tmp), source_root / "artifacts")
            with self.assertRaisesRegex(ValueError, "active runtime"):
                validate_isolated_paths(Path(tmp), ACTIVE_RUNTIME_DIR / "artifacts")

    def test_limits_and_stage_order_are_explicit(self) -> None:
        self.assertEqual(0, bounded_limit(0))
        with self.assertRaises(ValueError):
            bounded_limit(-1)
        self.assertEqual(("render", "ocr"), parse_stages("render,ocr"))
        self.assertEqual(("ocr",), parse_stages("ocr"))
        with self.assertRaises(ValueError):
            parse_stages("ocr,render")
        with self.assertRaisesRegex(RuntimeError, "localhost"):
            validate_ocr_configuration(
                profile_version="ocr-glm-v1",
                base_url="https://example.com/v1",
                timeout_seconds=120,
            )

    def test_seed_is_idempotent_and_creates_no_vlm_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
            source_row = SimpleNamespace(
                source_id="opaque-source",
                source_revision="opaque-source-r1",
                source_type="image",
                expected_unit_count=1,
            )
            manifest = SimpleNamespace(
                subject_id="SYNTHETIC-001",
                subject_source_revision="synthetic-source-contract-r1",
                sources=[source_row],
            )
            store.replace_eligibility_subject_sources(
                "synthetic-project",
                manifest.subject_id,
                manifest.subject_source_revision,
                [
                    {
                        "source_id": source_row.source_id,
                        "source_revision": source_row.source_revision,
                        "content_hash": "1" * 64,
                        "size_bytes": 100,
                        "media_class": "image",
                        "processing_unit_kind": "image",
                        "expected_unit_count": 1,
                    }
                ],
            )
            first = seed_jobs(
                store,
                {"synthetic-project": [manifest]},
                profile_version="ocr-glm-v1",
                max_new_jobs=1,
            )
            second = seed_jobs(
                store,
                {"synthetic-project": [manifest]},
                profile_version="ocr-glm-v1",
                max_new_jobs=1,
            )
            self.assertEqual(1, first["created"])
            self.assertEqual(1, second["replayed"])
            with store._connect() as connection:
                kinds = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT job_kind FROM eligibility_evidence_jobs"
                    )
                }
            self.assertEqual({"ocr"}, kinds)

    def test_reused_runtime_with_unrelated_job_fails_before_worker_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
            store.replace_eligibility_subject_sources(
                "unrelated-project",
                "UNRELATED-001",
                "unrelated-contract",
                [
                    {
                        "source_id": "unrelated-source",
                        "source_revision": "unrelated-source-r1",
                        "content_hash": "2" * 64,
                        "size_bytes": 1,
                        "media_class": "image",
                    }
                ],
            )
            fake_manifests = {
                "expected-project": [SimpleNamespace(subject_id="EXPECTED-001")]
            }
            with self.assertRaisesRegex(ValueError, "outside the fixed cohort"):
                validate_runtime_scope(store, fake_manifests)

    def test_empty_artifact_integrity_verification_is_safe(self) -> None:
        from services.api.app.eligibility_artifact_store import (
            EligibilityArtifactStore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SqliteRuntimeStore(root / "runtime.sqlite3")
            self.assertEqual(
                0,
                verify_artifact_integrity(
                    store,
                    EligibilityArtifactStore(root / "artifacts"),
                ),
            )

if __name__ == "__main__":
    unittest.main()
