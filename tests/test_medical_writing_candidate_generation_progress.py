from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from services.api.app.medical_writing import SectionAiCandidateExecutor
from tests.test_medical_writing_revision_durable import (
    PROJECTS,
    _build_echo_service,
    _initial_job,
)


class CandidateGenerationProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        (
            self.documents,
            _,
            self.repo,
            self.service,
            self.provider,
        ) = _build_echo_service(Path(self.tmpdir.name), tag="P")
        self.executor = SectionAiCandidateExecutor(self.service)
        self.project_id = PROJECTS[0]
        self.job, *_ = _initial_job(
            self.project_id,
            self.documents,
            service=self.service,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @staticmethod
    def _shape(progress):
        return [
            (
                item.phase,
                item.percent,
                item.step,
                item.step_total,
                item.message,
                tuple(item.model_dump(mode="json")),
            )
            for item in progress
        ]

    def test_blocked_provider_exposes_calling_ai_without_early_99_percent(self):
        provider_entered = threading.Event()
        provider_release = threading.Event()
        original_run = self.provider.run

        def blocking_run(envelope):
            provider_entered.set()
            if not provider_release.wait(timeout=10):
                raise TimeoutError("test provider was not released")
            return original_run(envelope)

        self.provider.run = blocking_run
        progress = []
        result_box = {}

        def execute():
            result_box["result"] = self.executor.execute(
                self.job,
                "claim-progress",
                lambda: False,
                lambda payload: progress.append(payload) or True,
            )

        worker = threading.Thread(target=execute)
        worker.start()
        try:
            self.assertTrue(
                provider_entered.wait(timeout=10),
                "fake provider was not reached",
            )
            current = progress[-1]
            self.assertEqual("calling_synthesis_ai", current.phase)
            self.assertEqual("正在调用综合AI", current.message)
            self.assertEqual(3, current.step)
            self.assertEqual(5, current.step_total)
            self.assertEqual(0.4, current.percent)
            self.assertLess(current.percent, 0.99)
            self.assertEqual(
                [
                    "validating_context",
                    "assembling_evidence_prompt",
                    "calling_synthesis_ai",
                ],
                [item.phase for item in progress],
            )
        finally:
            provider_release.set()
            worker.join(timeout=20)

        self.assertFalse(worker.is_alive())
        result = result_box["result"]
        self.assertFalse(result.error)
        self.assertEqual(
            [
                "validating_context",
                "assembling_evidence_prompt",
                "calling_synthesis_ai",
                "validating_candidates",
                "committing",
            ],
            [item.phase for item in progress],
        )
        self.assertEqual([1, 2, 3, 4, 5], [item.step for item in progress])
        self.assertTrue(
            all(
                current.percent <= following.percent
                for current, following in zip(progress, progress[1:])
            )
        )
        self.assertTrue(all(item.percent < 0.99 for item in progress))
        self.assertEqual(1.0, result.progress.percent)
        self.assertEqual(5, result.progress.step)
        self.assertEqual(5, result.progress.step_total)
        self.assertEqual("AI候选已生成并提交", result.progress.message)

    def test_retry_reuses_the_same_progress_field_contract(self):
        first_progress = []

        def lose_ownership_at_commit(payload):
            first_progress.append(payload)
            return payload.phase != "committing"

        first = self.executor.execute(
            self.job,
            "claim-first",
            lambda: False,
            lose_ownership_at_commit,
        )
        self.assertTrue(first.error)
        self.assertTrue(first.retryable)
        self.assertEqual([], self.repo.revision_threads(self.project_id))

        retry_progress = []
        retry = self.executor.execute(
            self.job,
            "claim-retry",
            lambda: False,
            lambda payload: retry_progress.append(payload) or True,
        )

        self.assertFalse(retry.error)
        self.assertEqual(self._shape(first_progress), self._shape(retry_progress))
        self.assertEqual(
            {"phase", "percent", "step", "step_total", "message"},
            set(retry_progress[0].model_dump(mode="json")),
        )
        self.assertEqual(1, len(self.repo.revision_threads(self.project_id)))


if __name__ == "__main__":
    unittest.main()
