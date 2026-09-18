"""Regression tests for the generic independent-AI frozen-route contract.

These tests pin the audit finding that ``AiTaskRunner`` used to resolve the
execution policy and then let the default provider factory re-read the dynamic
runtime route. The contract under test:

* one complete route identity (profile id/revision, provider, model,
  transport, base URL, required response model, deployment profile and a
  deterministic identity hash) is frozen at policy resolution;
* the default provider factory constructs the provider only from that frozen
  resolution, so a dynamic route mutation after resolution cannot change the
  constructed provider;
* any full-identity mismatch between the resolution and the created provider,
  or between the frozen route and the provider's actual response model, fails
  closed;
* ``AiTaskRun`` persists the frozen identity and the actual response model;
* injected test providers remain supported without weakening production
  fail-closed behavior.
"""

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
from services.api.app.ai_execution_policy import (  # noqa: E402
    AiExecutionPolicyDenied,
    AiExecutionPolicyResolver,
)
from services.api.app.ai_gateway import OpenAICompatibleAiProvider  # noqa: E402
from services.api.app.ai_runtime_settings import (  # noqa: E402
    AiProviderProfile,
    AiRuntimeSettingsStore,
)
from services.api.app.ai_task_runner import (  # noqa: E402
    AiTaskRunner,
    AiTaskStore,
    _configured_provider_factory,
)
from services.api.app.demo_repository import DemoRepository  # noqa: E402


PROJECT_ID = "proj_mgk10_sar_demo"
ROUTE_A_BASE_URL = "https://route-a.example.invalid/v1"
ROUTE_B_BASE_URL = "https://route-b.example.invalid/v1"


def _profile(profile_id: str, base_url: str, model: str) -> AiProviderProfile:
    return AiProviderProfile(
        profile_id=profile_id,
        provider="openai_compatible",
        label=f"Route {profile_id}",
        base_url=base_url,
        model=model,
        timeout_seconds=10.0,
        deployment_profile="local_private_clinical",
    )


def _write_role_binding(path: Path, profile_id: str, model: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "ai_role_bindings_v2",
                "revision": 1,
                "bindings": {
                    "independent_ai": {
                        "role_id": "independent_ai",
                        "profile_id": profile_id,
                        "model": model,
                        "enabled": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


class _FakeHttpResponse:
    def __init__(self, body: str):
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


def _fake_urlopen(captured: list, response_model: str = ""):
    """Return an urlopen double that answers a well-formed completion echo."""

    def _fake(request, timeout=0):
        payload = json.loads(request.data.decode("utf-8"))
        captured.append({"url": request.full_url, "payload": payload})
        envelope = json.loads(payload["messages"][1]["content"])
        content = {
            "task_id": envelope["task_id"],
            "task_type": envelope["task_type"],
            "provider": envelope["provider"],
            "model": envelope["model"],
            "prompt_version": envelope["prompt_version"],
            "input_source_ids": [
                source["source_id"] for source in envelope["allowed_sources"]
            ],
            "forbidden_source_ids": envelope["forbidden_source_ids"],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }
        body = {
            "model": response_model or payload["model"],
            "choices": [
                {"message": {"content": json.dumps(content, ensure_ascii=False)}}
            ],
        }
        return _FakeHttpResponse(json.dumps(body))

    return _fake


class _IdentityCarrier:
    """Test double exposing production-style route identity attributes."""

    def __init__(self, **attributes):
        self.provider_name = attributes.pop("provider_name", "openai_compatible")
        self.model_name = attributes.pop("model_name", "model-a")
        for name, value in attributes.items():
            setattr(self, name, value)
        self.ran = False

    def run(self, envelope):
        self.ran = True
        raise AssertionError("a route-mismatched provider must never run")


class FrozenRouteFixture:
    def __init__(self, test_case: unittest.TestCase):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings_path = root / "ai_provider_settings.json"
        self.role_path = root / "ai_role_bindings.json"
        self.store = AiRuntimeSettingsStore(self.settings_path)
        self.store.upsert(
            _profile("route_a", ROUTE_A_BASE_URL, "model-a"),
            api_key="route-a-key",
            activate=True,
        )
        _write_role_binding(self.role_path, "route_a", "model-a")
        self.env_patch = patch.dict(
            os.environ,
            {
                "WORKBENCH_AI_SETTINGS_PATH": str(self.settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(self.role_path),
            },
        )
        self.env_patch.start()
        test_case.addCleanup(self.env_patch.stop)
        test_case.addCleanup(self.tmp.cleanup)

    def mutate_to_route_b(self) -> None:
        self.store.upsert(
            _profile("route_b", ROUTE_B_BASE_URL, "model-b"),
            api_key="route-b-key",
            activate=True,
        )
        _write_role_binding(self.role_path, "route_b", "model-b")


class AiRouteFreezeTests(unittest.TestCase):
    def setUp(self):
        self.repo = DemoRepository(
            PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
        )
        self.source = AiTaskSourceRef(
            source_id="protocol_span_001",
            source_type="protocol_docx_span",
            title="研究方案 V2.1",
            locator="docx:p120",
            text_preview="随机前需完成禁限用药洗脱。",
            project_id=PROJECT_ID,
            module="medical_monitoring",
        )
        self.request = AiTaskRequest(
            module="medical_monitoring",
            task_type="monitoring_risk_interpretation",
            prompt_version="monitoring_risk_interpretation_v0_1",
            allowed_sources=[self.source],
            user_instruction="请仅基于原始方案 span 解释医学监查风险。",
        )

    def _runner(self, tmp: Path, resolver, provider_factory=None) -> AiTaskRunner:
        kwargs = {}
        if provider_factory is not None:
            kwargs["provider_factory"] = provider_factory
        return AiTaskRunner(
            self.repo,
            AiTaskStore(tmp / "ai_runs.jsonl"),
            policy_resolver=resolver,
            **kwargs,
        )

    def test_resolution_freezes_complete_route_identity(self):
        FrozenRouteFixture(self)
        resolution = AiExecutionPolicyResolver().resolve_internal(
            PROJECT_ID, self.request
        )

        self.assertEqual("route_a", resolution.route_profile_id)
        self.assertEqual(1, resolution.route_profile_revision)
        self.assertEqual("openai_compatible", resolution.provider_name)
        self.assertEqual("model-a", resolution.model_name)
        self.assertEqual("openai_compatible", resolution.transport_name)
        self.assertEqual(ROUTE_A_BASE_URL, resolution.base_url)
        self.assertEqual("model-a", resolution.required_response_model)
        self.assertEqual("local_private_clinical", resolution.deployment_profile)
        self.assertEqual(10.0, resolution.route_timeout_seconds)
        self.assertEqual(64, len(resolution.route_identity_hash))

        same = AiExecutionPolicyResolver().resolve_internal(PROJECT_ID, self.request)
        self.assertEqual(resolution.route_identity_hash, same.route_identity_hash)

    def test_route_identity_hash_changes_with_route_mutation(self):
        fixture = FrozenRouteFixture(self)
        before = AiExecutionPolicyResolver().resolve_internal(PROJECT_ID, self.request)
        fixture.mutate_to_route_b()
        after = AiExecutionPolicyResolver().resolve_internal(PROJECT_ID, self.request)

        self.assertEqual("route_b", after.route_profile_id)
        self.assertEqual("model-b", after.model_name)
        self.assertNotEqual(before.route_identity_hash, after.route_identity_hash)

    def test_public_route_snapshot_matches_resolution_and_contains_no_credential(self):
        FrozenRouteFixture(self)
        resolver = AiExecutionPolicyResolver()
        snapshot = resolver.route_identity_snapshot()
        resolution = resolver.resolve_internal(PROJECT_ID, self.request)

        self.assertEqual(
            "independent_ai_route_snapshot_v1", snapshot["schema_version"]
        )
        self.assertEqual("independent_ai", snapshot["role_id"])
        self.assertEqual("route_a", snapshot["profile_id"])
        self.assertEqual(
            resolution.route_identity_hash, snapshot["identity_sha256"]
        )
        self.assertNotIn("api_key", json.dumps(snapshot, ensure_ascii=False).lower())
        self.assertNotIn("route-a-key", json.dumps(snapshot, ensure_ascii=False))

    def test_default_factory_builds_provider_only_from_frozen_resolution(self):
        fixture = FrozenRouteFixture(self)
        resolution = AiExecutionPolicyResolver().resolve_internal(
            PROJECT_ID, self.request
        )
        fixture.mutate_to_route_b()

        provider = _configured_provider_factory(resolution)

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual(ROUTE_A_BASE_URL, provider.base_url)
        self.assertEqual("model-a", provider.model_name)
        self.assertEqual("openai_compatible", provider.provider_name)
        self.assertEqual("openai_compatible", provider.transport_name)
        self.assertEqual("model-a", provider.expected_response_model)
        self.assertEqual("route-a-key", provider.api_key)
        self.assertEqual(10.0, provider.timeout_seconds)

    def test_dynamic_route_mutation_during_execution_cannot_change_provider(self):
        fixture = FrozenRouteFixture(self)
        captured_requests = []
        seen_resolutions = []

        def mutating_factory(resolution):
            seen_resolutions.append(resolution)
            # The dynamic route flips after policy resolution but before the
            # provider is constructed, the exact audit reproduction condition.
            fixture.mutate_to_route_b()
            return _configured_provider_factory(resolution)

        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(
                Path(tmp),
                AiExecutionPolicyResolver(),
                provider_factory=mutating_factory,
            )
            with patch(
                "urllib.request.urlopen", _fake_urlopen(captured_requests)
            ):
                run = runner.submit_internal(PROJECT_ID, self.request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
        self.assertEqual(1, len(captured_requests))
        self.assertTrue(
            captured_requests[0]["url"].startswith(ROUTE_A_BASE_URL),
            captured_requests[0]["url"],
        )
        self.assertEqual("model-a", captured_requests[0]["payload"]["model"])
        resolution = seen_resolutions[0]
        self.assertEqual("route_a", resolution.route_profile_id)
        self.assertEqual("route_a", run.route_profile_id)
        self.assertEqual(1, run.route_profile_revision)
        self.assertEqual(ROUTE_A_BASE_URL, run.route_base_url)
        self.assertEqual("openai_compatible", run.route_transport)
        self.assertEqual("model-a", run.expected_response_model)
        self.assertEqual("model-a", run.actual_response_model)
        self.assertEqual(resolution.route_identity_hash, run.route_identity_hash)
        # The mutation really happened: a fresh resolution now sees route B.
        current = AiExecutionPolicyResolver().resolve_internal(
            PROJECT_ID, self.request
        )
        # The post-execution role binding is normalized into its own profile;
        # endpoint/model identity, not the old unscoped label, proves mutation.
        self.assertEqual("independent_ai__route_b", current.route_profile_id)
        self.assertEqual(ROUTE_B_BASE_URL, current.base_url)
        self.assertEqual("model-b", current.model_name)
        self.assertNotEqual(
            current.route_identity_hash, resolution.route_identity_hash
        )

    def test_full_identity_mismatch_with_created_provider_fails_closed(self):
        FrozenRouteFixture(self)
        cases = {
            "provider configuration mismatch": _IdentityCarrier(
                provider_name="unexpected-provider"
            ),
            "model configuration mismatch": _IdentityCarrier(
                model_name="unexpected-model"
            ),
            "transport configuration mismatch": _IdentityCarrier(
                transport_name="hermes_cli"
            ),
            "base URL configuration mismatch": _IdentityCarrier(
                transport_name="openai_compatible",
                base_url=ROUTE_B_BASE_URL,
                expected_response_model="model-a",
            ),
            "expected response model configuration mismatch": _IdentityCarrier(
                transport_name="openai_compatible",
                base_url=ROUTE_A_BASE_URL,
                expected_response_model="model-b",
            ),
        }
        for message, provider in cases.items():
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as tmp:
                    runner = self._runner(
                        Path(tmp),
                        AiExecutionPolicyResolver(),
                        provider_factory=lambda resolution: provider,
                    )
                    with self.assertRaisesRegex(
                        AiExecutionPolicyDenied, message
                    ):
                        runner.submit_internal(PROJECT_ID, self.request)
                    self.assertFalse(provider.ran)
                    self.assertEqual(
                        [], runner.list_runs(PROJECT_ID),
                        "a denied execution must not persist a run record",
                    )

    def test_endpoint_response_model_mismatch_fails_closed(self):
        FrozenRouteFixture(self)
        captured_requests = []
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(Path(tmp), AiExecutionPolicyResolver())
            with patch(
                "urllib.request.urlopen",
                _fake_urlopen(captured_requests, response_model="model-b"),
            ):
                run = runner.submit_internal(PROJECT_ID, self.request)

        self.assertEqual(AiTaskRunStatus.FAILED, run.status)
        self.assertTrue(
            any("response model identity" in error for error in run.validation_errors),
            run.validation_errors,
        )
        self.assertEqual("model-a", run.expected_response_model)
        self.assertEqual("model-b", run.actual_response_model)

    def test_injected_test_provider_remains_supported_with_static_route_identity(
        self,
    ):
        class InjectedProvider:
            provider_name = "buddy"
            model_name = "deepseek-v4-pro"

            def run(self, envelope):
                return {
                    "task_id": envelope.task_id,
                    "task_type": envelope.task_type.value,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt_version": envelope.prompt_version,
                    "input_source_ids": ["protocol_span_001"],
                    "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
                    "findings": [],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "needs_medical_confirmation": True,
                    "schema_version": "ai_task_output_v0_1",
                }

        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
            test_only_provider_injection=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(
                Path(tmp),
                resolver,
                provider_factory=lambda resolution: InjectedProvider(),
            )
            run = runner.submit_internal(PROJECT_ID, self.request)

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
        self.assertEqual("", run.route_profile_id)
        self.assertEqual(0, run.route_profile_revision)
        self.assertEqual("openai_compatible", run.route_transport)
        self.assertEqual("", run.route_base_url)
        self.assertEqual("deepseek-v4-pro", run.expected_response_model)
        self.assertEqual("", run.actual_response_model)
        self.assertEqual(64, len(run.route_identity_hash))

    def test_credential_bearing_base_url_is_never_persisted(self):
        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="openai_compatible",
            model_name="model-a",
            base_url="https://user:secret@route-c.example.invalid/v1",
            test_only_provider_injection=True,
        )

        class InjectedProvider:
            provider_name = "openai_compatible"
            model_name = "model-a"

            def run(self, envelope):
                return {
                    "task_id": envelope.task_id,
                    "task_type": envelope.task_type.value,
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "prompt_version": envelope.prompt_version,
                    "input_source_ids": ["protocol_span_001"],
                    "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
                    "findings": [],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "needs_medical_confirmation": True,
                    "schema_version": "ai_task_output_v0_1",
                }

        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner(
                Path(tmp),
                resolver,
                provider_factory=lambda resolution: InjectedProvider(),
            )
            run = runner.submit_internal(PROJECT_ID, self.request)
            persisted = (Path(tmp) / "ai_runs.jsonl").read_text(encoding="utf-8")

        self.assertEqual(AiTaskRunStatus.COMPLETED, run.status)
        self.assertEqual(
            "https://route-c.example.invalid/v1", run.route_base_url
        )
        self.assertNotIn("secret", persisted)
        self.assertNotIn("user:secret", persisted)


if __name__ == "__main__":
    unittest.main()
