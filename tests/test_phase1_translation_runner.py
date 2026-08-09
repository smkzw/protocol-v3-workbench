import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "records"
    / "active_slices"
    / "medical_writing_phase1_autoimmune_mnc_corpus_20260716"
    / "run_production_translations.py"
)
SPEC = importlib.util.spec_from_file_location("phase1_translation_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase1TranslationRunnerTests(unittest.TestCase):
    def write_notes(self, payload):
        temp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(payload, temp)
        temp.close()
        self.addCleanup(Path(temp.name).unlink)
        return Path(temp.name)

    def test_loads_bounded_medical_review_notes(self):
        path = self.write_notes(
            {
                "schema_version": "phase1_translation_medical_review_notes_v1",
                "notes": [{"segment_id": "s1", "instruction": "统一术语。"}],
            }
        )
        notes = MODULE.load_medical_review_notes(path, [{"segment_id": "s1"}])
        self.assertEqual(notes, {"s1": "统一术语。"})

    def test_rejects_unknown_review_note_segment(self):
        path = self.write_notes(
            {
                "schema_version": "phase1_translation_medical_review_notes_v1",
                "notes": [{"segment_id": "unknown", "instruction": "统一术语。"}],
            }
        )
        with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
            MODULE.load_medical_review_notes(path, [{"segment_id": "s1"}])

    def test_rejects_empty_review_note(self):
        path = self.write_notes(
            {
                "schema_version": "phase1_translation_medical_review_notes_v1",
                "notes": [{"segment_id": "s1", "instruction": ""}],
            }
        )
        with self.assertRaisesRegex(ValueError, "invalid or duplicate"):
            MODULE.load_medical_review_notes(path, [{"segment_id": "s1"}])


if __name__ == "__main__":
    unittest.main()
