from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SOURCE = (
    ROOT / "frontend/src/features/writing-reference/WritingReferencePanel.jsx"
)
SHARED_PANEL_SOURCE = (
    ROOT / "frontend/src/features/writing-reference/SharedPhase1CorpusPanel.jsx"
)
AUTHORING_SOURCE = (
    ROOT
    / "frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx"
)


class FrontendMedicalWritingSharedCorpusContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = REFERENCE_SOURCE.read_text(encoding="utf-8")
        cls.panel = SHARED_PANEL_SOURCE.read_text(encoding="utf-8")
        cls.authoring = AUTHORING_SOURCE.read_text(encoding="utf-8")

    def test_phase1_shared_corpus_is_authoring_only_and_phase_gated(self):
        self.assertIn('{ id: "shared_phase1", label: "I期共享语料" }', self.reference)
        self.assertIn("const phase1SharedAvailable = authoringMode && isPhase1(", self.reference)
        self.assertIn('view.id !== "shared_phase1" || phase1SharedAvailable', self.reference)
        self.assertIn('activeView === "shared_phase1" && phase1SharedAvailable', self.reference)
        self.assertIn('"I/II期"', self.reference)
        self.assertIn(
            'lockedPhase={journey.framing?.study_phase || ""}',
            self.authoring,
        )

    def test_review_surface_shows_source_translation_and_secondary_lineage(self):
        self.assertIn("Protocol原文", self.panel)
        self.assertIn("监管中文候选", self.panel)
        self.assertIn("selected.source_text", self.panel)
        self.assertIn("selected.translated_text", self.panel)
        self.assertIn("来源与版本", self.panel)
        self.assertIn("selected.source_locator", self.panel)
        self.assertIn("selected.source_url", self.panel)

    def test_review_admission_and_withdrawal_actions_use_shared_corpus_api(self):
        for route in (
            "/api/medical-writing/shared-corpus/phase1?",
            "/api/medical-writing/shared-corpus/phase1/${selected.segment_id}/medical-review",
            "/api/medical-writing/shared-corpus/phase1/${selected.segment_id}/admissions",
        ):
            self.assertIn(route, self.panel)
        for decision in ('review("approved")', 'review("returned")', 'review("rejected")'):
            self.assertIn(decision, self.panel)
        self.assertIn("纳入I期共享语料", self.panel)
        self.assertIn("撤回并退回修订", self.panel)

    def test_project_facts_are_explicitly_out_of_scope(self):
        for term in ("药物", "剂量", "阈值", "访视", "终点", "当前项目事实"):
            self.assertIn(term, self.panel)


if __name__ == "__main__":
    unittest.main()
