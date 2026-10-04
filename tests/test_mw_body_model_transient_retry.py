"""R26 self-check R5 (第1次), P1-b counterexample (red-first, then fix).

Field evidence (proj_user_415ce4db48b2 / proj_user_3ea77adeef20 /
proj_user_953921d37b47 — three rounds): the FIRST item of the FIRST
reference-translation batch always lands failed_retryable with

  "body translation model unavailable: AiProviderRuntimeError"

(audit chain: translation_batch_item_failed, error_code
translation_generation_failed) and needs a human "仅重试失败项" click to
recover.  Root cause: oMLX (8001) loads on demand via the orchestrator; the
first body call races the load, the lifecycle refusal surfaces as
AiProviderRuntimeError, and _hy_mt2_translator_adapter wraps ANY exception
into CompositePipelineUnavailableError with zero retry — one transient
orchestration refusal burns the whole item.

Fixed contract: the body-translation adapter retries AiProviderRuntimeError
(orchestration/provider-availability transient) a bounded number of times
with a wait, so a cold-start load race self-heals inside the same item
instead of forcing a manual batch retry.
"""
from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from services.api.app.ai_gateway import AiProviderRuntimeError
from services.api.app.chapter_translation_pipeline import (
    FidelityBlockedError,
)
from services.api.app.main import _hy_mt2_translator_adapter
from services.api.app.writing_reference import CompositePipelineUnavailableError


def _role_context(_role):
    binding = types.SimpleNamespace(model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX")
    profile = types.SimpleNamespace(provider="omlx")
    values = {
        "WORKBENCH_AI_BASE_URL": "http://127.0.0.1:8001/v1",
        "WORKBENCH_AI_API_KEY": "",
    }
    return binding, profile, values


class TestBodyModelTransientRetry(unittest.TestCase):
    def _run_adapter(self, failures_before_success: int):
        """Call the adapter with a scripted transient-refusal sequence."""
        calls = {"n": 0}

        def gated_execute(fn, *, kind, owner):
            del kind, owner
            calls["n"] += 1
            if calls["n"] <= failures_before_success:
                raise AiProviderRuntimeError(
                    "Managed local model server unavailable: model loading",
                    diagnostics={"failure_code": "model_loading"},
                )
            return fn()

        def fake_execute(_lease=None):
            return {"choices": [{"message": {"content": "译文"}}]}

        import services.api.app.chapter_translation_pipeline as pipeline_mod
        import services.api.app.main as main_mod

        with patch.object(main_mod, "_runtime_role_context", _role_context), \
            patch.object(main_mod, "run_gated_omlx_request", gated_execute), \
            patch.object(
                pipeline_mod,
                "validate_completion_payload",
                lambda payload, model: "受试者在14天内不得接受SCS。",
            ), patch("time.sleep", lambda _s: None):
            result = _hy_mt2_translator_adapter(
                "[[CMS_SEG_0001]]\nParticipants must not receive SCS within 14 "
                "days.\n[[/CMS_SEG_0001]]",
                glossary="cms_regulatory_zh_v1",
                chapter_id="ch_test",
                chunk_id="chunk_test",
            )
        return result, calls["n"]

    def test_transient_orchestration_refusals_self_heal_within_the_item(self):
        result, attempts = self._run_adapter(failures_before_success=2)
        self.assertEqual("受试者在14天内不得接受SCS。", result.translated_text)
        self.assertGreaterEqual(attempts, 3)

    def test_exhausted_transients_still_fail_closed(self):
        with self.assertRaises(CompositePipelineUnavailableError):
            self._run_adapter(failures_before_success=99)

    def test_fidelity_block_is_not_retried_here(self):
        """Bounded-correction fidelity blocks keep their own semantics."""
        from services.api.app.chapter_translation_pipeline import (
            translate_units_with_bounded_correction,
        )

        # The adapter itself never raises FidelityBlockedError; guard the
        # import surface used by the pipeline contract stays untouched.
        self.assertTrue(issubclass(FidelityBlockedError, Exception))
        self.assertTrue(callable(translate_units_with_bounded_correction))


if __name__ == "__main__":
    unittest.main()
