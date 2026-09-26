from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    AiTaskRequest,
    AiTaskRunStatus,
    AiTaskSourceRef,
)
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver  # noqa: E402
from services.api.app.ai_role_runtime_settings import (  # noqa: E402
    INDEPENDENT_AI_MTPLX_MODEL,
)
from services.api.app.ai_gateway import AiProviderRuntimeError  # noqa: E402
from services.api.app.ai_runtime_settings import (  # noqa: E402
    AiFallbackRoute,
    AiProviderProfile,
    AiRuntimeSettingsStore,
)
from services.api.app.ai_task_runner import (  # noqa: E402
    AI_FALLBACK_TASKS,
    AiTaskRunner,
    AiTaskStore,
)
from services.api.app.ai_gateway import AiTaskType  # noqa: E402
from services.api.app.demo_repository import DemoRepository  # noqa: E402


PROJECT_ID = "proj_fallback_contract"
# The served MTPLX API id per the approved direct route
# (_MTPLX_QWEN38_SPEED_POLICY); the HF-style directory name is not accepted.
MTPLX_MODEL = INDEPENDENT_AI_MTPLX_MODEL


def _profile(profile_id: str, provider: str, base_url: str, model: str, effort: str):
    return AiProviderProfile(
        profile_id=profile_id,
        provider=provider,
        label=profile_id,
        base_url=base_url,
        model=model,
        expected_response_model=model,
        deployment_scope="loopback" if base_url.startswith("http://127.0.0.1") else "cloud",
        api_key_env="TEST_AI_KEY" if not base_url.startswith("http://127.0.0.1") else "",
        thinking="enabled",
        reasoning_effort=effort,
    )


class _Provider:
    def __init__(self, resolution, *, failure_status: int | None = None, invalid=False):
        self.provider_name = resolution.provider_name
        self.model_name = resolution.model_name
        self.response_model = resolution.required_response_model
        self.failure_status = failure_status
        self.invalid = invalid

    def run(self, envelope):
        if self.failure_status is not None:
            raise AiProviderRuntimeError(
                f"HTTP {self.failure_status}",
                diagnostics={
                    "failure_code": "provider_http_error",
                    "http_status": self.failure_status,
                },
            )
        if self.invalid:
            return {"invalid": True}
        source = envelope.payload["allowed_sources"][0]
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [source["source_id"]],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [],
            "evidence_spans": [{
                "span_id": "ev_1",
                "source_id": source["source_id"],
                "locator": source["locator"],
                "quote": source["text_preview"],
            }],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {
                "sections": [{
                    "section_id": section_id,
                    "content_status": "complete",
                    "proposal_text": "本研究将依照当前项目已经确认的研究设计和实施要求开展。" * 5,
                    "rationale": "依据当前项目来源形成候选。",
                    "evidence_span_ids": ["ev_1"],
                    "decision_items": [],
                    "missing_source_classes": [],
                    "gap_items": [],
                } for section_id in envelope.payload["task_context"]["section_ids"]],
            },
        }


class _RegisteredResolver(AiExecutionPolicyResolver):
    def __init__(self, canonical_request):
        super().__init__()
        self.canonical_request = canonical_request

    def resolve_registered(self, project_id, request, source_registry):
        return self.resolve_internal(project_id, self.canonical_request)

    def resolve_registered_for_profile(
        self, project_id, request, source_registry, profile
    ):
        return self.resolve_internal_for_profile(
            project_id, self.canonical_request, profile
        )


class AiFallbackChainTests(unittest.TestCase):
    def setUp(self):
        self.repo = DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json")
        self.request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_full_draft",
            prompt_version="protocol_full_draft_v0_11",
            allowed_sources=[AiTaskSourceRef(
                source_id="full_draft_packet",
                source_type="protocol_full_draft_selection",
                title="当前项目研究设计",
                locator="study_definition:v1",
                text_preview="本研究为随机、双盲、安慰剂对照的III期临床研究。",
                project_id=PROJECT_ID,
                module="medical_writing",
            )],
            user_instruction="生成章节正文。",
            task_context={
                "draft_version": "a" * 64,
                "section_ids": ["section_1"],
                "marker_open": "SECTION_ID=",
                "marker_close": "\n",
                "minimum_body_chars": 80,
                "decision_fact_paths": [],
            },
        )

    def _fixture(self, root: Path):
        settings_path = root / "ai_provider_settings.json"
        role_path = root / "ai_role_bindings.json"
        store = AiRuntimeSettingsStore(settings_path)
        primary = _profile(
            "independent_ai__mtplx", "mtplx", "http://127.0.0.1:8002/v1", MTPLX_MODEL, "medium"
        )
        backup = _profile(
            "independent_ai__opencode", "opencode-go", "https://opencode.ai/zen/go/v1", "deepseek-v4.1-flash", "max"
        )
        store.upsert(primary, activate=True)
        store.upsert(backup, api_key="test-key", activate_if_empty=False)
        store.set_fallback_chain([AiFallbackRoute(profile_id=backup.profile_id)])
        role_path.write_text(json.dumps({
            "schema_version": "ai_role_bindings_v2",
            "revision": 1,
            "bindings": {"independent_ai": {
                "role_id": "independent_ai",
                "profile_id": primary.profile_id,
                "model": primary.model,
                "enabled": True,
                "thinking": "enabled",
                "reasoning_effort": "medium",
            }},
        }), encoding="utf-8")
        return store, settings_path, role_path

    def test_429_uses_next_profile_and_links_both_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, settings_path, role_path = self._fixture(root)
            seen = []

            def provider_factory(resolution):
                seen.append((resolution.route_profile_id, resolution.route_reasoning_effort))
                return _Provider(
                    resolution,
                    failure_status=429 if resolution.provider_name == "mtplx" else None,
                )

            with patch.dict(os.environ, {
                "WORKBENCH_AI_SETTINGS_PATH": str(settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            }):
                runner = AiTaskRunner(
                    self.repo,
                    AiTaskStore(root / "ai_runs.jsonl"),
                    provider_factory=provider_factory,
                    policy_resolver=AiExecutionPolicyResolver(),
                )
                result = runner.submit_internal(PROJECT_ID, self.request)
                runs = runner.list_runs(PROJECT_ID)

        self.assertEqual(AiTaskRunStatus.COMPLETED, result.status)
        self.assertEqual("opencode-go", result.provider)
        self.assertEqual(1, result.fallback_depth)
        self.assertEqual("provider_http_error:429", result.fallback_reason)
        self.assertEqual(runs[0].run_id, result.fallback_parent_run_id)
        self.assertEqual(runs[0].fallback_chain_id, result.fallback_chain_id)
        self.assertEqual(2, len(runs))
        self.assertEqual([
            ("independent_ai__mtplx", "medium"),
            ("independent_ai__opencode", "max"),
        ], seen)

    def test_content_validation_failure_does_not_change_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, settings_path, role_path = self._fixture(root)
            seen = []

            def provider_factory(resolution):
                seen.append(resolution.route_profile_id)
                return _Provider(resolution, invalid=True)

            with patch.dict(os.environ, {
                "WORKBENCH_AI_SETTINGS_PATH": str(settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            }):
                runner = AiTaskRunner(
                    self.repo,
                    AiTaskStore(root / "ai_runs.jsonl"),
                    provider_factory=provider_factory,
                    policy_resolver=AiExecutionPolicyResolver(),
                )
                result = runner.submit_internal(PROJECT_ID, self.request)
                runs = runner.list_runs(PROJECT_ID)

        self.assertEqual(AiTaskRunStatus.FAILED, result.status)
        self.assertEqual(["independent_ai__mtplx"], seen)
        self.assertEqual(1, len(runs))
        self.assertEqual(0, result.fallback_depth)

    def test_registered_request_uses_same_fallback_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, settings_path, role_path = self._fixture(root)
            seen = []

            def provider_factory(resolution):
                seen.append(resolution.route_profile_id)
                return _Provider(
                    resolution,
                    failure_status=503 if resolution.provider_name == "mtplx" else None,
                )

            with patch.dict(os.environ, {
                "WORKBENCH_AI_SETTINGS_PATH": str(settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            }):
                runner = AiTaskRunner(
                    self.repo,
                    AiTaskStore(root / "ai_runs.jsonl"),
                    provider_factory=provider_factory,
                    policy_resolver=_RegisteredResolver(self.request),
                )
                result = runner.submit_registered(PROJECT_ID, object(), object())

        self.assertEqual(AiTaskRunStatus.COMPLETED, result.status)
        self.assertEqual(1, result.fallback_depth)
        self.assertEqual("provider_http_error:503", result.fallback_reason)
        self.assertEqual(
            ["independent_ai__mtplx", "independent_ai__opencode"], seen
        )

    def test_ineligible_first_fallback_is_skipped_and_second_profile_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store, settings_path, role_path = self._fixture(root)
            ineligible = _profile(
                "ocr_profile", "omlx", "http://127.0.0.1:8000/v1", "GLM-OCR-bf16", "low"
            )
            second = _profile(
                "independent_ai__cms", "cms-router", "http://127.0.0.1:20128/v1", "deepseek-latest-cloud", "max"
            )
            store.upsert(ineligible, activate_if_empty=False)
            store.upsert(second, api_key="test-key", activate_if_empty=False)
            store.set_fallback_chain([
                AiFallbackRoute(profile_id=ineligible.profile_id),
                AiFallbackRoute(profile_id=second.profile_id),
            ])
            seen = []

            def provider_factory(resolution):
                seen.append(resolution.route_profile_id)
                return _Provider(
                    resolution,
                    failure_status=429 if resolution.provider_name == "mtplx" else None,
                )

            with patch.dict(os.environ, {
                "WORKBENCH_AI_SETTINGS_PATH": str(settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            }):
                runner = AiTaskRunner(
                    self.repo,
                    AiTaskStore(root / "ai_runs.jsonl"),
                    provider_factory=provider_factory,
                    policy_resolver=AiExecutionPolicyResolver(),
                )
                result = runner.submit_internal(PROJECT_ID, self.request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, result.status)
        self.assertEqual(2, result.fallback_depth)
        self.assertEqual(
            ["independent_ai__mtplx", "independent_ai__cms"], seen
        )

    def test_disabled_first_fallback_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store, settings_path, role_path = self._fixture(root)
            first = store.profile("independent_ai__opencode")
            second = _profile(
                "independent_ai__cms", "cms-router", "http://127.0.0.1:20128/v1", "deepseek-latest-cloud", "max"
            )
            store.upsert(second, api_key="test-key", activate_if_empty=False)
            store.set_fallback_chain([
                AiFallbackRoute(profile_id=first.profile_id),
                AiFallbackRoute(profile_id=second.profile_id),
            ])
            store.upsert(
                AiProviderProfile(**{**first.__dict__, "enabled": False}),
                activate_if_empty=False,
            )
            seen = []

            def provider_factory(resolution):
                seen.append(resolution.route_profile_id)
                return _Provider(
                    resolution,
                    failure_status=429 if resolution.provider_name == "mtplx" else None,
                )

            with patch.dict(os.environ, {
                "WORKBENCH_AI_SETTINGS_PATH": str(settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            }):
                runner = AiTaskRunner(
                    self.repo,
                    AiTaskStore(root / "ai_runs.jsonl"),
                    provider_factory=provider_factory,
                    policy_resolver=AiExecutionPolicyResolver(),
                )
                result = runner.submit_internal(PROJECT_ID, self.request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, result.status)
        self.assertEqual(2, result.fallback_depth)
        self.assertEqual(
            ["independent_ai__mtplx", "independent_ai__cms"], seen
        )

    def test_comprehensive_ai_tasks_share_the_fallback_chain(self):
        self.assertTrue({
            AiTaskType.COMPETITIVE_INTELLIGENCE,
            AiTaskType.PROTOCOL_DESIGN_SYNTHESIS,
            AiTaskType.PICOS_DESIGN_COACH,
        }.issubset(AI_FALLBACK_TASKS))


if __name__ == "__main__":
    unittest.main()
