from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.raw_subject_bundle import (  # noqa: E402
    inventory_subject_bundle,
    needs_ocr_vlm_for_source_type,
    source_type_for_suffix,
)


D001_PASS_DIR = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/全量-入组/白铭江/0316-SA07005"
)
D001_FAIL_DIR = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/全量-入组/白铭江/0316-SA07007-T-SPOT阳性导致筛败"
)
MGK10_RAW_DIR = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/enrollment-review-app/projects/MG-K10-SAR-III/subjects/31001/raw"
)


class RawSubjectBundleInventoryTests(unittest.TestCase):
    @unittest.skipUnless(D001_PASS_DIR.exists(), f"missing fixture: {D001_PASS_DIR}")
    def test_inventory_reads_d001_pass_bundle_with_pdf_zip_and_images(self):
        inventory = inventory_subject_bundle(D001_PASS_DIR)

        self.assertEqual(str(D001_PASS_DIR.resolve()), inventory.root_path)
        self.assertEqual(len(inventory.files), inventory.total_files)
        self.assertEqual(inventory.total_files, sum(inventory.source_type_counts.values()))
        self.assertGreaterEqual(inventory.source_type_counts.get("pdf", 0), 1)
        self.assertGreaterEqual(inventory.source_type_counts.get("zip", 0), 1)
        self.assertGreaterEqual(inventory.source_type_counts.get("image", 0), 1)
        self.assertEqual(
            inventory.source_type_counts.get("pdf", 0) + inventory.source_type_counts.get("image", 0),
            inventory.needs_ocr_vlm_count,
        )
        self.assertTrue(any(file.source_type == "zip" and not file.needs_ocr_vlm for file in inventory.files))
        self.assertEqual(
            sorted(file.relative_path.lower() for file in inventory.files),
            [file.relative_path.lower() for file in inventory.files],
        )

    @unittest.skipUnless(D001_FAIL_DIR.exists(), f"missing fixture: {D001_FAIL_DIR}")
    def test_inventory_reads_d001_screen_failure_bundle(self):
        inventory = inventory_subject_bundle(D001_FAIL_DIR)

        self.assertGreaterEqual(inventory.total_files, 1)
        self.assertGreaterEqual(inventory.source_type_counts.get("pdf", 0), 1)
        self.assertGreaterEqual(inventory.source_type_counts.get("zip", 0), 1)
        self.assertGreaterEqual(inventory.source_type_counts.get("image", 0), 1)
        self.assertTrue(all(Path(file.path).is_absolute() for file in inventory.files))
        self.assertTrue(all(not Path(file.relative_path).is_absolute() for file in inventory.files))
        self.assertTrue(all(file.size_bytes >= 0 for file in inventory.files))

    @unittest.skipUnless(MGK10_RAW_DIR.exists(), f"missing fixture: {MGK10_RAW_DIR}")
    def test_inventory_reads_mgk10_raw_subject_bundle(self):
        inventory = inventory_subject_bundle(MGK10_RAW_DIR)

        self.assertGreaterEqual(inventory.total_files, 1)
        self.assertEqual({"pdf"}, set(inventory.source_type_counts))
        self.assertEqual(inventory.total_files, inventory.source_type_counts["pdf"])
        self.assertEqual(inventory.total_files, inventory.needs_ocr_vlm_count)
        self.assertTrue(all(file.suffix == ".pdf" for file in inventory.files))

    def test_source_type_mapping_covers_doc_and_docx_without_content_access(self):
        expected = {
            ".pdf": "pdf",
            ".zip": "zip",
            ".doc": "doc",
            ".docx": "docx",
            ".JPG": "image",
            ".unknown": "other",
        }

        for suffix, source_type in expected.items():
            with self.subTest(suffix=suffix):
                self.assertEqual(source_type, source_type_for_suffix(suffix))

        self.assertTrue(needs_ocr_vlm_for_source_type("pdf"))
        self.assertTrue(needs_ocr_vlm_for_source_type("image"))
        self.assertFalse(needs_ocr_vlm_for_source_type("docx"))
        self.assertFalse(needs_ocr_vlm_for_source_type("zip"))


if __name__ == "__main__":
    unittest.main()
