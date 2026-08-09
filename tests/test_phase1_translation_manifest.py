import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "records"
    / "active_slices"
    / "medical_writing_phase1_autoimmune_mnc_corpus_20260716"
    / "build_medical_review_manifest.py"
)
SPEC = importlib.util.spec_from_file_location("phase1_translation_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase1TranslationManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        source_file = self.root / "protocol.pdf"
        source_file.write_bytes(b"protocol")
        source_text = "A single dose will be administered."
        self.selection = {
            "segment_id": "segment-1",
            "nct_id": "NCT00000001",
            "sponsor": "Sponsor",
            "modality": "small_molecule",
            "compound": "Test drug",
            "corpus_function": "single_dose",
            "source_file": str(source_file),
            "source_url": "https://cdn.clinicaltrials.gov/test.pdf",
            "source_locator": "Protocol page 1",
            "source_text": source_text,
            "source_text_sha256": MODULE.sha256_text(source_text),
            "document_sha256": MODULE.sha256_bytes(source_file.read_bytes()),
            "selection_status": "translation_pending",
        }
        translated_text = "将进行单次给药。"
        self.candidate = {
            **self.selection,
            "translation_status": "medical_qa_pending",
            "final_pass": {
                "ai_run_id": "airun_test",
                "provider": "deepseek",
                "model_name": MODULE.REGULATORY_TRANSLATION_MODEL_NAME,
                "prompt_version": MODULE.REGULATORY_TRANSLATION_PROMPT_VERSION,
                "contract_hash": MODULE.REGULATORY_TRANSLATION_CONTRACT_HASH,
                "translated_text": translated_text,
                "translated_text_sha256": MODULE.sha256_text(translated_text),
                "fidelity_status": "passed",
                "fidelity_failure_codes": [],
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def build(self, candidate=None):
        selection_path = self.write_json("selection.json", [self.selection])
        candidate_path = self.write_json(
            "candidate.json", [candidate or self.candidate]
        )
        return MODULE.build_manifest(
            selection_path, [candidate_path], expected_count=1
        )

    def test_builds_pending_manifest_without_admission(self):
        manifest = self.build()
        self.assertEqual(manifest["automatic_gate_passed_count"], 1)
        self.assertEqual(manifest["medical_review_approved_count"], 0)
        self.assertEqual(manifest["corpus_admitted_count"], 0)
        self.assertEqual(manifest["items"][0]["medical_review_status"], "pending")
        self.assertEqual(
            manifest["items"][0]["corpus_admission_status"], "not_admitted"
        )

    def test_rejects_stale_contract(self):
        candidate = deepcopy(self.candidate)
        candidate["final_pass"]["contract_hash"] = "stale"
        with self.assertRaisesRegex(ValueError, "invalid contract_hash"):
            self.build(candidate)

    def test_rejects_failed_fidelity_gate(self):
        candidate = deepcopy(self.candidate)
        candidate["final_pass"]["fidelity_status"] = "blocked"
        candidate["final_pass"]["fidelity_failure_codes"] = ["test_failure"]
        with self.assertRaisesRegex(ValueError, "invalid fidelity_status"):
            self.build(candidate)

    def test_rejects_stale_source_text_hash(self):
        self.selection["source_text_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "invalid source_text_sha256"):
            self.build()

    def test_rejects_missing_source_file(self):
        self.selection.pop("source_file")
        with self.assertRaisesRegex(ValueError, "missing.*source_file"):
            self.build()

    def test_rejects_stale_document_hash(self):
        self.selection["document_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "stale document_sha256"):
            self.build()

    def test_rejects_duplicate_current_candidate(self):
        selection_path = self.write_json("selection.json", [self.selection])
        candidate_a = self.write_json("candidate-a.json", [self.candidate])
        candidate_b = self.write_json("candidate-b.json", [self.candidate])
        with self.assertRaisesRegex(ValueError, "multiple current passing candidates"):
            MODULE.build_manifest(
                selection_path, [candidate_a, candidate_b], expected_count=1
            )

    def test_resolves_source_file_relative_to_slice_root(self):
        relative_source = self.root / "raw" / "documents" / "protocol.pdf"
        relative_source.parent.mkdir(parents=True)
        relative_source.write_bytes(b"relative-protocol")
        self.selection["source_file"] = "raw/documents/protocol.pdf"
        self.selection["document_sha256"] = MODULE.sha256_bytes(
            relative_source.read_bytes()
        )
        translations = self.root / "translations"
        translations.mkdir()
        selection_path = translations / "selection.json"
        selection_path.write_text(json.dumps([self.selection]), encoding="utf-8")
        candidate = deepcopy(self.candidate)
        candidate.update(self.selection)
        candidate_path = self.write_json("candidate.json", [candidate])
        manifest = MODULE.build_manifest(
            selection_path, [candidate_path], expected_count=1
        )
        self.assertEqual(manifest["automatic_gate_passed_count"], 1)


if __name__ == "__main__":
    unittest.main()
