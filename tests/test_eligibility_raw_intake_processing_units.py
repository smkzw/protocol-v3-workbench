from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf

from services.api.app.eligibility_raw_intake import (
    EligibilityRawProjectIntakeService,
    RawEligibilityProjectConfig,
)


class EligibilityRawIntakeProcessingUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EligibilityRawProjectIntakeService(ai_provider_configured=False)

    def test_public_sources_report_deterministic_expected_processing_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject_dir = root / "S00001"
            subject_dir.mkdir()

            pdf_path = subject_dir / "a-record.pdf"
            with pymupdf.open() as document:
                for _ in range(3):
                    document.new_page()
                document.save(pdf_path)

            for filename in (
                "b-image.png",
                "c-record.doc",
                "d-record.docx",
                "e-bundle.zip",
                "f-bundle.rar",
                "g-unknown.bin",
            ):
                (subject_dir / filename).write_bytes(b"source")

            payload = self.service.subject_manifest(
                RawEligibilityProjectConfig(
                    project_id="proj_processing_units",
                    protocol_path=pdf_path,
                    raw_subject_root=root,
                ),
                "S00001",
            ).public_dict(include_sources=True)

        by_suffix = {source["suffix"]: source for source in payload["sources"]}
        self.assertEqual(
            ("page", 3, "known"),
            self._unit_metadata(by_suffix[".pdf"]),
        )
        self.assertEqual(("image", 1, "known"), self._unit_metadata(by_suffix[".png"]))
        self.assertEqual(("document", 1, "known"), self._unit_metadata(by_suffix[".doc"]))
        self.assertEqual(("document", 1, "known"), self._unit_metadata(by_suffix[".docx"]))
        self.assertEqual(
            ("archive_container", 1, "known"),
            self._unit_metadata(by_suffix[".zip"]),
        )
        self.assertEqual(
            ("archive_container", 1, "known"),
            self._unit_metadata(by_suffix[".rar"]),
        )
        self.assertEqual(("file", 1, "known"), self._unit_metadata(by_suffix[".bin"]))

    def test_unreadable_pdf_reports_unknown_zero_count_instead_of_inventing_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject_dir = root / "S00001"
            subject_dir.mkdir()
            pdf_path = subject_dir / "broken.pdf"
            pdf_path.write_bytes(b"not-a-readable-pdf")

            source = self.service.subject_manifest(
                RawEligibilityProjectConfig(
                    project_id="proj_unreadable_pdf",
                    protocol_path=pdf_path,
                    raw_subject_root=root,
                ),
                "S00001",
            ).public_dict(include_sources=True)["sources"][0]

        self.assertEqual("page", source["unit_kind"])
        self.assertEqual(0, source["expected_unit_count"])
        self.assertEqual("unknown_unreadable_pdf", source["expected_unit_count_status"])

    @staticmethod
    def _unit_metadata(source: dict[str, object]) -> tuple[object, object, object]:
        return (
            source["unit_kind"],
            source["expected_unit_count"],
            source["expected_unit_count_status"],
        )


if __name__ == "__main__":
    unittest.main()
