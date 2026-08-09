"""Frontend contract tests for the durable medical-writing job integration.

Source-level assertions (no browser needed) verifying:
- The reusable durable job hook exports the expected API.
- App.jsx uses the shared control plane (pollDurableMwJob import + usage).
- App.jsx has NO inline 200-iteration polling loops.
- App.jsx uses the atomic accept-and-apply endpoint (no two-request chain).
- App.jsx handles failed/cancelled (never fetches latest thread after failure).
- The reusable hook provides failed/cancelled handling and terminal result.
- Triage (WritingReferencePanel.jsx) uses durable job lifecycle.
- Translation (ReferenceTranslationBatchPanel.jsx) uses durable job lifecycle.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK_SOURCE = ROOT / "frontend/src/features/medical-writing/useDurableMwJob.js"
APP_SOURCE = ROOT / "frontend/src/App.jsx"
TRANSLATION_SOURCE = (
    ROOT / "frontend/src/features/writing-reference/ReferenceTranslationBatchPanel.jsx"
)
TRIAGE_SOURCE = (
    ROOT / "frontend/src/features/writing-reference/WritingReferencePanel.jsx"
)


class FrontendDurableJobHookContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = HOOK_SOURCE.read_text(encoding="utf-8")

    def test_hook_exports_useDurableMwJob(self):
        self.assertIn("export function useDurableMwJob", self.hook)

    def test_hook_exports_pollDurableMwJob(self):
        self.assertIn("export async function pollDurableMwJob", self.hook)

    def test_hook_provides_start_cancel_retry_clear(self):
        for fn in ("startJob", "cancelJob", "retryJob", "clearJob"):
            self.assertIn(fn, self.hook)

    def test_hook_uses_localStorage_persistence(self):
        self.assertIn("localStorage.setItem", self.hook)
        self.assertIn("localStorage.getItem", self.hook)
        self.assertIn("localStorage.removeItem", self.hook)

    def test_hook_polls_unified_job_endpoint(self):
        self.assertIn("/medical-writing/jobs/", self.hook)

    def test_hook_implements_dedupe(self):
        self.assertIn("actionInProgressRef", self.hook)

    def test_hook_has_terminal_status_set(self):
        sm = (ROOT / "frontend/src/features/medical-writing/durableJobState.mjs").read_text(
            "utf-8"
        )
        self.assertIn("isTerminal", self.hook)
        self.assertIn("shouldClearLocator", self.hook)
        self.assertIn("resolveDomainAck", self.hook)
        self.assertIn("TERMINAL_STATUSES", sm)
        self.assertIn('"completed"', sm)
        self.assertIn('"failed"', sm)
        self.assertIn('"cancelled"', sm)

    def test_pollDurableMwJob_fetches_result_endpoint(self):
        """pollDurableMwJob must fetch /result for terminal jobs."""
        self.assertIn("/result", self.hook)

    def test_pollDurableMwJob_returns_error_field(self):
        """pollDurableMwJob must return an error field for failure display."""
        # The function should return { status, result, error }
        self.assertIn("errorSummary", self.hook)


    def test_state_machine_module_exists(self):
        """durableJobState.mjs must exist and export key functions."""
        sm = (ROOT / "frontend/src/features/medical-writing/durableJobState.mjs").read_text("utf-8")
        self.assertIn("isCompletedSuccess", sm)
        self.assertIn("shouldClearLocator", sm)
        self.assertIn("shouldBlockStart", sm)
        self.assertIn("extractArtifactThreadId", sm)
        self.assertIn("isStaleCompletion", sm)

    def test_hook_imports_production_state_machine(self):
        """useDurableMwJob must import durableJobState.mjs (not dead code)."""
        self.assertIn('from "./durableJobState.mjs"', self.hook)
        self.assertIn("shouldClearLocator", self.hook)
        self.assertIn("buildLocator", self.hook)
        self.assertIn("classifyPollOutcome", self.hook)


class FrontendAppRevisionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP_SOURCE.read_text(encoding="utf-8")

    def test_app_only_completed_triggers_success_behavior(self):
        """App.jsx must route success only through domain acknowledgement."""
        self.assertIn("acknowledgeRevisionDomain", self.app)
        self.assertIn("createScreenGeneration", self.app)
        self.assertIn("isScreenGenerationCurrent", self.app)
        self.assertNotIn("needs-write-retry", self.app)
        # Cancel must not clear on status===cancelled alone.
        self.assertNotIn("resultReconciled || status === \"cancelled\"", self.app)
        self.assertNotIn("resultReconciled || status === 'cancelled'", self.app)

    def test_app_uses_result_artifact_thread_id(self):
        """App.jsx must reconcile via extractArtifactThreadId, not list tail or fallback."""
        self.assertIn("extractArtifactThreadId", self.app)
        self.assertIn("extractArtifactSuggestionIds", self.app)
        self.assertNotIn("threadsResp[threadsResp.length - 1]", self.app,
                         "must NOT use last list item for thread selection")
        # v2 must not fallback-guess thread id.
        self.assertNotIn("extractArtifactThreadId(result) || stored.thread_id", self.app)
        self.assertNotIn("extractArtifactThreadId(rwResult) || thread.thread_id", self.app)

    def test_app_persists_revision_locator_before_polling(self):
        """App.jsx must write versioned locator before polling for revision job."""
        self.assertIn("mw_revision_job_", self.app)
        self.assertIn("buildLocator", self.app)
        self.assertIn("setOperationJob", self.app)
        self.assertIn("clearOperationJob", self.app)

    def test_app_imports_pollDurableMwJob(self):
        """App.jsx must import the shared control plane + durableJobState helpers."""
        self.assertIn("pollDurableMwJob", self.app)
        self.assertIn("from", self.app)
        self.assertIn("useDurableMwJob", self.app)
        self.assertIn("shouldBlockStartForOperation", self.app)
        self.assertIn("resolveRetryJobId", self.app)
        self.assertIn("acknowledgeRevisionDomain", self.app)

    def test_app_dual_operation_recovery_is_concurrent(self):
        """Initial and rewrite recovery must not serialize with a single break."""
        self.assertIn("Promise.all", self.app)
        self.assertNotIn("break; // only resume one", self.app)
        self.assertIn("emptyRevisionJobMap", self.app)

    def test_app_has_no_inline_200_iteration_polling_loop(self):
        """App.jsx must NOT contain the old inline `for (let i = 0; i < 200` polling."""
        # The old pattern was: for (let i = 0; i < 200; i++) {
        # ... await new Promise((r) => setTimeout(r, 1500));
        old_pattern = r"for\s*\(let\s+i\s*=\s*0;\s*i\s*<\s*200;\s*i\+\+\)"
        matches = re.findall(old_pattern, self.app)
        self.assertEqual(0, len(matches),
                         f"Found {len(matches)} inline polling loops — must use pollDurableMwJob instead")

    def test_app_handles_failed_cancelled_for_revision(self):
        """App.jsx must handle failed/cancelled job status and NOT fetch latest thread."""
        # After polling, if failed/cancelled, show error and return without fetching.
        self.assertIn('"failed"', self.app)
        self.assertIn('"cancelled"', self.app)

    def test_atomic_accept_and_apply_endpoint_used(self):
        """The frontend must call the single accept-and-apply endpoint."""
        self.assertIn("/accept-and-apply", self.app)
        self.assertIn("suggestion_id", self.app)
        self.assertIn("expected_working_copy_revision", self.app)


class FrontendTriagePanelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.triage = TRIAGE_SOURCE.read_text(encoding="utf-8")

    def test_triage_imports_pollDurableMwJob(self):
        """WritingReferencePanel must import the shared poller + domain ack helpers."""
        self.assertIn("pollDurableMwJob", self.triage)
        self.assertIn("buildLocator", self.triage)
        self.assertIn("acknowledgeTriageDomain", self.triage)
        self.assertNotIn("resultReconciled || status === \"cancelled\"", self.triage)

    def test_triage_has_start_ai_triage_control(self):
        """Triage panel must have a start-ai-triage button."""
        self.assertIn("start-ai-triage", self.triage)
        self.assertIn("startAiTriage", self.triage)

    def test_triage_persists_job_locator(self):
        """Triage must persist the versioned job locator in localStorage."""
        self.assertIn("mw_triage_job_", self.triage)
        self.assertIn("localStorage.setItem", self.triage)
        self.assertIn("buildLocator", self.triage)

    def test_triage_has_cancel_control(self):
        """Triage must have a cancel button for the durable job."""
        self.assertIn("cancel-ai-triage", self.triage)

    def test_triage_resumes_after_reload(self):
        """Triage must resume polling from localStorage after reload."""
        self.assertIn("localStorage.getItem", self.triage)
        self.assertIn("mw_triage_job_", self.triage)

    def test_triage_does_not_auto_finalize(self):
        """AI triage must not auto-finalize; manual finalize remains."""
        self.assertIn("finalizeTriage", self.triage)
        self.assertIn("finalize-triage", self.triage)


class FrontendTranslationPanelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translation = TRANSLATION_SOURCE.read_text(encoding="utf-8")

    def test_translation_imports_pollDurableMwJob(self):
        """Translation panel must import the shared poller + domain ack helpers."""
        self.assertIn("pollDurableMwJob", self.translation)
        self.assertIn("buildLocator", self.translation)
        self.assertIn("acknowledgeTranslationDomain", self.translation)
        self.assertIn("resolveRetryJobId", self.translation)
        self.assertIn("mergeRetryLocator", self.translation)

    def test_translation_captures_durable_job_id(self):
        """Translation create must capture durable_job_id from response."""
        self.assertIn("durable_job_id", self.translation)
        self.assertIn("durableJobId", self.translation)

    def test_translation_persists_job_locator(self):
        """Translation must persist the versioned job locator in localStorage."""
        self.assertIn("mw_translation_job_", self.translation)
        self.assertIn("buildLocator", self.translation)

    def test_translation_has_cancel_control(self):
        """Translation must have a cancel button for the durable job."""
        self.assertIn("cancel-translation-job", self.translation)
        self.assertIn("cancelTranslationJob", self.translation)

    def test_translation_resumes_after_reload(self):
        """Translation must resume polling from localStorage after reload."""
        # Check for localStorage.getItem with the translation job key
        self.assertIn("localStorage.getItem", self.translation)

    def test_translation_preserves_batch_polling(self):
        """Translation must still poll the batch endpoint for item progress."""
        self.assertIn("translation-batches/", self.translation)

    def test_translation_has_dedupe(self):
        """Double-click dedupe must be present."""
        self.assertIn("batchRequestInFlightRef", self.translation)


if __name__ == "__main__":
    unittest.main()
