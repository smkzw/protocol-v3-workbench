from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    AiTaskFromRegistryRequest,
    AiTaskRequest,
    AiTaskSourceRef,
)
from services.api.app.ai_execution_policy import (
    AiExecutionPolicyDenied,
    AiExecutionPolicyResolver,
    MTPLX_LOCAL_BASE_URL,
    TASK_AI_ROUTE_POLICIES,
)
from services.api.app.ai_role_runtime_settings import INDEPENDENT_AI_MTPLX_MODEL
from services.api.app.ai_gateway import AiPromptEnvelope, AiTaskType
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore, public_ai_run
from services.api.app.demo_repository import DemoRepository
from services.api.app.main import app
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal
from services.api.app.source_intake import SourceRegistryService, SourceRegistryStore
from tests.test_source_registry import _minimal_xlsx_bytes


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
PROJECT_ID = "proj_mgk10_sar_demo"


class RecordingProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(
        self,
        *,
        provider_override="",
        model_override="",
        prompt_override="",
        unsafe_evidence=False,
    ):
        self.calls = []
        self.provider_override = provider_override
        self.model_override = model_override
        self.prompt_override = prompt_override
        self.unsafe_evidence = unsafe_evidence

    def run(self, envelope: AiPromptEnvelope):
        self.calls.append(envelope)
        source = envelope.payload["allowed_sources"][0]
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_override or self.provider_name,
            "model": self.model_override or self.model_name,
            "prompt_version": self.prompt_override or envelope.prompt_version,
            "input_source_ids": [source["source_id"]],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "字段映射候选",
                    "source_id": source["source_id"],
                    "evidence_span_ids": ["span_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": source["source_id"],
                    "locator": (
                        "/Users/private/evidence.xlsx"
                        if self.unsafe_evidence
                        else source["locator"]
                    ),
                    "quote": (
                        "CONFIDENTIAL PATIENT TEXT /Users/private/source.xlsx"
                        if self.unsafe_evidence
                        else source["text_preview"]
                    ),
                }
            ],
            "uncertainties": [
                {"level": "medical_review", "description": "需医学经理确认。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }


class NeverCalledRunner:
    def __init__(self):
        self.called = False

    def submit_registered(self, *args, **kwargs):
        self.called = True
        raise AssertionError("direct source payload route must not reach the AI runner")


class ProviderFactory:
    def __init__(self, provider):
        self.provider = provider
        self.calls = []

    def __call__(self, resolution):
        self.calls.append(resolution)
        return self.provider


class LazyProviderFactory:
    def __init__(self):
        self.calls = []
        self.provider = None

    def __call__(self, resolution):
        self.calls.append(resolution)
        self.provider = RecordingProvider()
        return self.provider


class AiExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = DemoRepository(
            PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
        )
        self.registry = SourceRegistryService(
            SourceRegistryStore(self.root / "sources.jsonl")
        )
        self.registered = self.registry.register_listing_file(
            PROJECT_ID,
            "edc_listing.xlsx",
            _minimal_xlsx_bytes(),
            module="medical_monitoring",
        )
        self.source_id = self.registered.spans[0].source_id

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="ai-execution-policy-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=(PROJECT_ID,),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="ai-execution-policy-test-session",
            directory_revision="ai-execution-policy-test-v1",
            verification_ref_sha256="a" * 64,
        )

    def request(self, **updates):
        payload = {
            "module": "medical_monitoring",
            "task_type": "listing_semantic_mapping",
            "expected_prompt_version": "listing_semantic_mapping_v0_1",
            "source_ids": [self.source_id],
            "forbidden_source_ids": ["client_excluded_reference"],
            "user_instruction": "仅基于登记的原始 listing 建议字段映射。",
        }
        payload.update(updates)
        return AiTaskFromRegistryRequest(**payload)

    def runner(self, provider):
        provider_factory = ProviderFactory(provider)
        return AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
            ),
        )

    def test_medical_writing_defaults_prefer_local_mtplx_qwen(self):
        for task_type in (
            AiTaskType.MEDICAL_WRITING_REVISION,
            AiTaskType.PROTOCOL_FULL_DRAFT,
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            AiTaskType.DOCUMENT_SECTION_EXTRACTION,
            AiTaskType.REGULATORY_TRANSLATION_ZH,
        ):
            policy = TASK_AI_ROUTE_POLICIES[task_type][0]
            self.assertEqual("mtplx", policy.provider_name)
            self.assertEqual("openai_compatible", policy.transport_name)
            self.assertEqual(MTPLX_LOCAL_BASE_URL, policy.base_url)
            self.assertEqual(
                # The served API id (INDEPENDENT_AI_MTPLX_MODEL), not the
                # HF-style directory name.
                INDEPENDENT_AI_MTPLX_MODEL,
                next(iter(policy.allowed_models)),
            )

    def test_protocol_synopsis_structuring_gets_long_task_timeout_and_ladder_budget(self):
        """ENV-02 反例（资源预算层）：整份方案结构化抽取是长生成任务，300 秒
        单请求窗把它逼进 3×300 秒假失败循环（R26 现场第 1 次尝试耗尽 30 分钟
        报"未就绪"，第 2 次尝试负载缓解后 2.4 分钟即完成）。该任务类需要独立
        的长超时窗与重试梯子总预算；其他任务类保持现行预算不变。"""
        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="openai_compatible",
            model_name="loopback-test",
            test_only_provider_injection=True,
        )

        def _request(task_type: str, prompt_version: str) -> AiTaskRequest:
            return AiTaskRequest(
                module="medical_writing",
                task_type=task_type,
                prompt_version=prompt_version,
                allowed_sources=[
                    AiTaskSourceRef(
                        source_id="src_synopsis_docx",
                        source_type="document",
                        title="方案摘要",
                        locator="/tmp/synopsis.docx",
                        text_preview="方案摘要内容。适应症为哮喘。",
                        project_id="proj_timeout_tier",
                        module="medical_writing",
                    )
                ],
                user_instruction="结构化提取研究框架与PICOS。",
            )

        long_resolution = resolver.resolve_internal(
            "proj_timeout_tier",
            _request(
                "protocol_synopsis_structuring",
                "protocol_synopsis_structuring_v0_9",
            ),
        )
        self.assertEqual(1200.0, long_resolution.route_timeout_seconds)
        self.assertEqual(1800.0, long_resolution.route_ladder_budget_seconds)

        control = resolver.resolve_internal(
            "proj_timeout_tier",
            _request(
                "document_section_extraction",
                "document_section_extraction_v0_1",
            ),
        )
        self.assertEqual(300.0, control.route_timeout_seconds)
        self.assertEqual(0.0, control.route_ladder_budget_seconds)

    def test_profile_rebuild_keeps_long_task_timeout_and_ladder_budget(self):
        """ENV-02 反例（生产路径）：independent_ai 角色走 resolve_internal_for_profile，
        其 replace() 不得把分级超时回退成 profile 自带的 300 秒——否则 R26 的
        30 分钟假失败循环在生产路径原样复发。"""
        from types import SimpleNamespace

        from services.api.app.ai_execution_policy import (
            AiExecutionPolicyResolver as _Resolver,
        )

        resolver = _Resolver(
            deployment_profile="local_private_clinical",
            provider_name="openai_compatible",
            model_name="loopback-test",
            test_only_provider_injection=True,
        )
        profile = SimpleNamespace(
            profile_id="fake-mtplx",
            revision=3,
            provider="mtplx",
            model="mtplx-flash-next-optimized-speed",
            base_url="http://127.0.0.1:8002/v1",
            transport="openai_compatible",
            expected_response_model="mtplx-flash-next-optimized-speed",
            deployment_profile="local_private_clinical",
            timeout_seconds=300.0,
            api_key_env="",
            thinking="enabled",
            reasoning_effort="xhigh",
            enabled=True,
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="protocol_synopsis_structuring",
            prompt_version="protocol_synopsis_structuring_v0_9",
            allowed_sources=[
                AiTaskSourceRef(
                    source_id="src_synopsis_docx",
                    source_type="document",
                    title="方案摘要",
                    locator="/tmp/synopsis.docx",
                    text_preview="方案摘要内容。适应症为哮喘。",
                    project_id="proj_timeout_tier",
                    module="medical_writing",
                )
            ],
            user_instruction="结构化提取研究框架与PICOS。",
        )
        resolution = resolver.resolve_internal_for_profile(
            "proj_timeout_tier", request, profile
        )
        self.assertEqual(1200.0, resolution.route_timeout_seconds)
        self.assertEqual(1800.0, resolution.route_ladder_budget_seconds)

    def test_medical_writing_revision_policy_accepts_plan_pin_only_as_known_optional_key(self):
        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="openai_compatible",
            model_name="loopback-test",
            test_only_provider_injection=True,
        )
        context = {
            "revision_intent": "medical_writing_revision",
            "intent_label": "改写",
            "directional_goal": "在不改变事实的前提下规范表达。",
            "preservation_rules": ["不得新增事实。"],
            "candidate_count": 3,
            "candidate_blueprints": ["标准版", "精炼版", "保守版"],
            "protocol_assembly_plan": {
                "plan_id": "plan-001",
                "plan_revision": 2,
                "plan_sha256": "b" * 64,
            },
        }
        normalized = resolver._validate_medical_writing_revision_context(context)
        self.assertEqual("plan-001", normalized["protocol_assembly_plan"]["plan_id"])
        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "task_context keys must match"
        ):
            resolver._validate_medical_writing_revision_context(
                {**context, "unexpected": True}
            )

    def test_direct_allowed_sources_api_is_fail_closed_before_runner_or_provider(self):
        fake_runner = NeverCalledRunner()
        client = TestClient(app)
        response = None
        with patch("services.api.app.main.ai_task_runner", fake_runner):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs",
                json={
                    "module": "medical_monitoring",
                    "task_type": "listing_semantic_mapping",
                    "prompt_version": "attacker_selected_prompt",
                    "allowed_sources": [
                        {
                            "source_id": "forged_source",
                            "source_type": "forged",
                            "title": "forged",
                            "locator": "/Users/private/forged.xlsx",
                            "text_preview": "forged patient data",
                        }
                    ],
                },
            )

        self.assertEqual(403, response.status_code)
        self.assertIn("registered source IDs", response.json()["detail"])
        self.assertFalse(fake_runner.called)

    def test_cross_module_source_is_denied_without_provider_call(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "same module"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(
                    module="eligibility_review",
                    task_type="protocol_rule_extraction",
                    expected_prompt_version="protocol_rule_extraction_v0_1",
                ),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_registered_source_eligibility_review_requires_trusted_batch_service(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "trusted server batch service"
        ):
            runner.submit_registered(
                PROJECT_ID,
                self.request(
                    module="eligibility_review",
                    task_type="eligibility_rule_review",
                    expected_prompt_version="eligibility_rule_review_v0_1",
                ),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_task_module_mismatch_is_denied_without_provider_call(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "not allowed in module"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(task_type="medical_writing_revision"),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_revision_task_owner_profile_passes_execution_route_whitelist(self):
        """NEW-40（R27 第3轮修订）反例：NEW-22 把修订任务的提交层路由指向了
        owner 决策的 ollama-cloud（independent_ai__ollama_cloud_dsv41，
        base_url=https://ollama.com，模型 deepseek-v4.1-flash），但执行层
        TASK_AI_ROUTE_POLICIES[MEDICAL_WRITING_REVISION] 白名单没有
        ollama-cloud 策略项——_enforce_task_ai_route_policy 每次尝试
        AiExecutionPolicyDenied，mwjob_859f4055 三连拒后 failed，
        ollama.com 从未被实际调用。期望：owner 决策路由必须通过执行层白名单。
        """
        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="ollama-cloud",
            model_name="deepseek-v4.1-flash",
            transport_name="openai_compatible",
            # 0930 fix 后策略钉住 https://ollama.com/v1（adapter 直接拼
            # /chat/completions，缺 /v1 会 404）；本夹具此前用无 /v1 的
            # 旧端点，与已提交的生产修复脱节，属陈旧夹具而非行为断言。
            base_url="https://ollama.com/v1",
        )
        # 修前留痕：该路由曾触发 AiExecutionPolicyDenied（provider must be
        # one of alibaba_token_plan, cms-router, deepseek, mtplx,
        # opencode-go——不含 ollama-cloud），即 mwjob_859f4055 三连拒本体。
        # 修后契约：owner 决策冻结路由必须通过执行层白名单。
        self.assertIsNone(
            resolver._enforce_task_ai_route_policy(
                AiTaskType.MEDICAL_WRITING_REVISION
            )
        )

    def test_revision_task_routes_to_owner_decided_profile_not_chain_order(self):
        """NEW-22（R27 第2轮修订）反例：owner 决策（2026-09-28 修正）要求
        MEDICAL_WRITING_REVISION 走 ollama-cloud deepseek-v4.1-flash
        （independent_ai__ollama_cloud_dsv41），但 _capture_revision_cloud_route
        泛取 fallback 链第一个 enabled 云 profile——链首是
        independent_ai__opencode_go_deepseek_v41_flash 时修订任务被送到了
        opencode 网关（实测 mwjob_3dc3f0fa 的 route_profile_id 即 opencode）。
        期望：任务级路由表优先解析，ollama_cloud_dsv41 存在且 enabled 时
        修订路由必须落它；该 profile 不存在/禁用时才回退链序。
        """
        import tempfile as _tempfile

        from services.api.app.ai_runtime_settings import (
            AiFallbackRoute,
            AiProviderProfile,
            AiRuntimeSettingsStore,
        )

        with _tempfile.TemporaryDirectory() as tmp:
            store = AiRuntimeSettingsStore(Path(tmp) / "settings.json")
            opencode = AiProviderProfile(
                profile_id="independent_ai__opencode_go_deepseek_v41_flash",
                provider="opencode-go",
                label="OpenCode Go",
                base_url="https://opencode.ai/zen/go/v1",
                model="deepseek-v4.1-flash",
                api_key_env="OPENCODE_API_KEY",
                deployment_scope="cloud",
                discovery_mode="manual_plus_probe",
            )
            ollama = AiProviderProfile(
                profile_id="independent_ai__ollama_cloud_dsv41",
                provider="ollama-cloud",
                label="Ollama Cloud DSV41",
                base_url="https://ollama.com",
                model="deepseek-v4.1-flash",
                api_key_env="OLLAMA_CLOUD_API_KEY",
                deployment_scope="cloud",
                discovery_mode="manual_plus_probe",
            )
            local = AiProviderProfile(
                profile_id="independent_ai__mtplx_local",
                provider="mtplx",
                label="本地 MTPLX",
                base_url="http://127.0.0.1:8002/v1",
                model="mtplx-flash",
                deployment_scope="loopback",
                discovery_mode="models_endpoint",
            )
            store.upsert(local, activate=True)
            store.upsert(opencode)
            store.upsert(ollama)
            # 链里只有 opencode：ollama_cloud_dsv41 已定义且 enabled 但不在链中
            # ——这正是 NEW-22 现场（active=本地 MTPLX，链首=opencode 云）。
            store.set_fallback_chain(
                [AiFallbackRoute(profile_id=opencode.profile_id)]
            )

            resolver = AiExecutionPolicyResolver()
            with patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                resolver._capture_revision_cloud_route()

            self.assertEqual(
                "independent_ai__ollama_cloud_dsv41",
                resolver.route_profile_id,
                "修订任务必须落在 owner 决策指定的 ollama-cloud profile，"
                "而不是 fallback 链第一个云 profile",
            )

    def _owner_route_table_store(self, tmp: str):
        """SMOKE-r1-1 根因1现场复刻：active=本地 MTPLX（xhigh）、链首=
        opencode 云、owner 指定的 ollama_cloud_dsv41 已定义且 enabled 但
        不在 fallback 链中。"""
        from services.api.app.ai_runtime_settings import (
            AiFallbackRoute,
            AiProviderProfile,
            AiRuntimeSettingsStore,
        )

        store = AiRuntimeSettingsStore(Path(tmp) / "settings.json")
        store.upsert(
            AiProviderProfile(
                profile_id="independent_ai__mtplx_qwen38_local",
                provider="mtplx",
                label="本地 MTPLX",
                base_url="http://127.0.0.1:8002/v1",
                model="mtplx-flash-next-optimized-speed",
                deployment_scope="loopback",
                discovery_mode="models_endpoint",
            ),
            activate=True,
        )
        opencode = AiProviderProfile(
            profile_id="independent_ai__opencode_go_deepseek_v41_flash",
            provider="opencode-go",
            label="OpenCode Go",
            base_url="https://opencode.ai/zen/go/v1",
            model="deepseek-v4.1-flash",
            api_key_env="OPENCODE_API_KEY",
            deployment_scope="cloud",
            discovery_mode="manual_plus_probe",
        )
        store.upsert(opencode)
        store.upsert(
            AiProviderProfile(
                profile_id="independent_ai__ollama_cloud_dsv41",
                provider="ollama-cloud",
                label="Ollama Cloud DSV41",
                base_url="https://ollama.com/v1",
                model="deepseek-v4.1-flash",
                api_key_env="OLLAMA_CLOUD_API_KEY",
                deployment_scope="cloud",
                discovery_mode="manual_plus_probe",
            )
        )
        store.set_fallback_chain([AiFallbackRoute(profile_id=opencode.profile_id)])
        return store

    def test_cloud_tier_tasks_route_to_owner_decided_profile(self):
        """SMOKE-r1-1 根因1反例：owner 决策（2026-09-28）的完整路由表要求
        竞品分诊/研究设计综合/PICOS 辅导走 ollama-cloud
        deepseek-v4.1-flash，但 TASK_TYPE_ROUTE_PROFILE_OVERRIDES 此前只有
        medical_writing_revision——分诊经角色绑定主路落本地 MTPLX xhigh
        （durable 实证 mwjob_7b72ebc6a4eda816682ab3d1，
        base_url=127.0.0.1:8002/v1），26 批×重推理档与并发全文初稿互拖
        排队 38 分钟未完成。期望：三个云档任务在提交层身份
        （route_identity_snapshot）与 resolve_internal/resolve_registered
        解析里都落 owner 指定云 profile。
        """
        import tempfile as _tempfile

        from services.api.app.ai_execution_policy import (
            TASK_TYPE_ROUTE_PROFILE_OVERRIDES,
        )

        cloud_tasks = (
            "competitive_intelligence",
            "protocol_design_synthesis",
            "picos_design_coach",
        )
        for task_value in cloud_tasks:
            self.assertEqual(
                "independent_ai__ollama_cloud_dsv41",
                TASK_TYPE_ROUTE_PROFILE_OVERRIDES[task_value],
                f"{task_value} 必须在任务级路由表中",
            )
        with _tempfile.TemporaryDirectory() as tmp:
            store = self._owner_route_table_store(tmp)
            with patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                for task_value in cloud_tasks:
                    resolver = AiExecutionPolicyResolver()
                    snapshot = resolver.route_identity_snapshot(
                        task_type=task_value
                    )
                    self.assertEqual(
                        "independent_ai__ollama_cloud_dsv41",
                        snapshot["profile_id"],
                        f"{task_value} 提交层身份必须落 owner 云 profile",
                    )
                    self.assertEqual(
                        "https://ollama.com/v1",
                        snapshot["base_url"],
                        f"{task_value} 必须实际打到 ollama.com",
                    )

    def test_cloud_tier_override_falls_back_to_chain_order_when_missing(self):
        """配置缺口永不拒绝服务：owner 指定 profile 缺失时，云档任务按
        NEW-22 既有语义回退 fallback 链第一个 enabled 云 profile
        （仍是云档，不是本地绑定主路），route_identity_snapshot 不抛错。"""
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as tmp:
            store = self._owner_route_table_store(tmp)
            # 删除 owner 指定的 ollama profile（模拟配置缺口）
            payload = store.load()
            payload["profiles"] = [
                item
                for item in payload["profiles"]
                if item["profile_id"] != "independent_ai__ollama_cloud_dsv41"
            ]
            store.save(payload)
            with patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                resolver = AiExecutionPolicyResolver()
                snapshot = resolver.route_identity_snapshot(
                    task_type="competitive_intelligence"
                )
            self.assertEqual(
                "independent_ai__opencode_go_deepseek_v41_flash",
                snapshot["profile_id"],
                "配置缺口时云档任务按链序回退云 profile（NEW-22 语义），"
                "而非拒绝服务或回落本地 MTPLX",
            )

    def test_registered_path_applies_cloud_tier_override(self):
        """SMOKE-r1-1 根因1补充：resolve_registered（注册源入口）此前完全
        不应用任务级路由表；云档任务不应因入口不同而漂移回绑定主路。
        用 resolve_internal（内部源入口）验证同一表格生效。"""
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as tmp:
            store = self._owner_route_table_store(tmp)
            with patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                resolver = AiExecutionPolicyResolver()
                request = AiTaskRequest(
                    module="evidence_design",
                    task_type="competitive_intelligence",
                    prompt_version="competitive_intelligence_v0_1",
                    allowed_sources=[
                        AiTaskSourceRef(
                            source_id="src_001",
                            source_type="public_registry_record",
                            title="登记记录",
                            locator="nct:1",
                            text_preview="...",
                            project_id=PROJECT_ID,
                            module="evidence_design",
                        )
                    ],
                    user_instruction="竞品调研",
                )
                resolution = resolver.resolve_internal(PROJECT_ID, request)
            self.assertEqual(
                "independent_ai__ollama_cloud_dsv41",
                resolution.route_profile_id,
                "内部源入口的云档任务也必须落 owner 云 profile",
            )

    def test_full_draft_route_stays_on_bound_local_primary(self):
        """SMOKE-r1-2 ⑤ 补充：PROTOCOL_FULL_DRAFT 不在任务级云路由表内——
        全文初稿按 owner 决策（2026-09-28）留在绑定主路（本地 MTPLX），
        提交层身份不得被泛化到云端。"""
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as tmp:
            store = self._owner_route_table_store(tmp)
            with patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                resolver = AiExecutionPolicyResolver()
                snapshot = resolver.route_identity_snapshot(
                    task_type="protocol_full_draft"
                )
            self.assertEqual(
                "independent_ai__mtplx_qwen38_local",
                snapshot["profile_id"],
                "全文初稿必须留在绑定主路（本地 MTPLX）",
            )

    def test_revision_task_gets_long_request_window(self):
        """SMOKE-r1-3 ⑦（R27 收敛修订）反例：医学修订是重上下文结构化生成，
        ollama 云档 effort=max 下单请求合理耗时超过 profile 默认 600s 窗。
        r2 实证（airun_20260930170310）每次尝试都在 600s 被 TimeoutError
        杀掉、重试×回退把墙钟拖到 ~55 分钟；r3 同型 job 15.5 分钟仍无返回。
        期望：修订任务获得 synopsis 同档长窗（单请求 1200s），预算允许
        主路两次完整尝试（2400s），且档位不缩短更长配置。"""
        from services.api.app.ai_execution_policy import (
            TASK_TYPE_ROUTE_LADDER_BUDGET_SECONDS,
            TASK_TYPE_ROUTE_TIMEOUT_SECONDS,
        )

        self.assertEqual(
            1200.0, TASK_TYPE_ROUTE_TIMEOUT_SECONDS["medical_writing_revision"]
        )
        self.assertEqual(
            2400.0,
            TASK_TYPE_ROUTE_LADDER_BUDGET_SECONDS["medical_writing_revision"],
        )
        resolver = AiExecutionPolicyResolver()
        timeout, budget = resolver._route_budgets_for_task(
            AiTaskType.MEDICAL_WRITING_REVISION
        )
        self.assertEqual(1200.0, timeout)
        self.assertEqual(2400.0, budget)

    def test_prompt_version_is_server_selected_and_client_mismatch_is_denied(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "prompt version mismatch"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(expected_prompt_version="attacker_prompt_v9"),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_policy_denial_occurs_before_provider_factory_is_called(self):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "factory_guard_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )
        with self.assertRaises(AiExecutionPolicyDenied):
            runner.submit_registered(
                PROJECT_ID,
                self.request(expected_prompt_version="attacker_prompt_v9"),
                self.registry,
            )

        self.assertEqual([], provider_factory.calls)
        self.assertIsNone(provider_factory.provider)

    def test_client_exclusions_can_only_restrict_and_cannot_overlap_selected_sources(
        self,
    ):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "selected and forbidden"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(forbidden_source_ids=[self.source_id]),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_sensitive_listing_is_denied_for_document_only_deployment_profile(self):
        provider = RecordingProvider()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "restricted_profile_ai_runs.jsonl"),
            provider_factory=ProviderFactory(provider),
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="approved_private_documents",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "sensitive_subject_data"):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual([], provider.calls)

    def test_valid_registered_source_reaches_provider_with_server_policy(self):
        provider = RecordingProvider()
        run = self.runner(provider).submit_registered(
            PROJECT_ID,
            self.request(),
            self.registry,
        )

        self.assertEqual("completed", run.status)
        self.assertEqual("sensitive_subject_data", run.data_classification)
        self.assertEqual("local_private_clinical", run.deployment_profile)
        self.assertEqual("registered_sources", run.request_origin)
        self.assertTrue(run.policy_decision_id.startswith("policy_"))
        self.assertEqual(1, len(provider.calls))
        envelope = provider.calls[0]
        self.assertEqual("listing_semantic_mapping_v0_1", envelope.prompt_version)
        self.assertIn(
            "client_excluded_reference", envelope.payload["forbidden_source_ids"]
        )
        self.assertIn("previous_ai_summary", envelope.payload["forbidden_source_ids"])
        self.assertTrue(envelope.payload["allowed_sources"][0]["text_preview"])

    def test_provider_identity_and_prompt_must_match_effective_server_decision(self):
        for provider in (
            RecordingProvider(provider_override="forged-provider"),
            RecordingProvider(model_override="forged-model"),
            RecordingProvider(prompt_override="forged-prompt"),
        ):
            with self.subTest(
                provider=provider.provider_override, model=provider.model_override
            ):
                run = self.runner(provider).submit_registered(
                    PROJECT_ID,
                    self.request(),
                    self.registry,
                )
                self.assertEqual("failed", run.status)
                self.assertTrue(
                    any("mismatch" in message for message in run.validation_errors),
                    run.validation_errors,
                )

    def test_provider_factory_identity_mismatch_is_denied_before_provider_run(self):
        provider = RecordingProvider()
        provider.provider_name = "unexpected-provider"
        factory = ProviderFactory(provider)
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "provider_mismatch_ai_runs.jsonl"),
            provider_factory=factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "provider configuration mismatch"
        ):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual(1, len(factory.calls))
        self.assertEqual([], provider.calls)

    def test_duplicate_requested_source_ids_are_denied_before_provider_factory(self):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "duplicate_source_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "duplicate source_ids"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(source_ids=[self.source_id, self.source_id]),
                self.registry,
            )

        self.assertEqual([], provider_factory.calls)

    def test_cross_module_source_id_collision_is_denied_before_provider_factory(self):
        conflicting = self.registered.model_copy(
            update={
                "entry": self.registered.entry.model_copy(
                    update={"module": "eligibility_review"}
                ),
                "spans": [
                    span.model_copy(update={"module": "eligibility_review"})
                    for span in self.registered.spans
                ],
            }
        )
        self.registry.store.append(conflicting)
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "ambiguous_source_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "ambiguous"):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual([], provider_factory.calls)

    def test_internal_source_requires_project_and_module_binding_before_provider_factory(
        self,
    ):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "internal_binding_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )
        forged_source = AiTaskSourceRef(
            source_id="forged_internal_source",
            source_type="protocol_section_selection",
            title="forged",
            locator="sections.1",
            text_preview="forged",
            project_id="proj_other_study",
            module="medical_writing",
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="medical_writing_revision",
            prompt_version="medical_writing_revision_v1_4",
            allowed_sources=[forged_source],
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "canonical project"):
            runner.submit_internal(PROJECT_ID, request)

        self.assertEqual([], provider_factory.calls)

    def test_legacy_run_store_is_atomically_rewritten_to_audit_safe_projection(self):
        provider = RecordingProvider(unsafe_evidence=True)
        runner = self.runner(provider)
        run = runner.submit_registered(PROJECT_ID, self.request(), self.registry)
        store_path = self.root / "ai_runs.jsonl"
        store_path.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        migrated = AiTaskStore(store_path)

        serialized = store_path.read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn(self.registered.spans[0].text_preview, serialized)
        self.assertEqual(
            [run.run_id], [item.run_id for item in migrated.list_runs(PROJECT_ID)]
        )
        backups = list(self.root.glob("ai_runs.jsonl.pre_audit_safe.*.bak"))
        self.assertEqual(1, len(backups))
        backup_serialized = backups[0].read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", backup_serialized)
        self.assertNotIn("/Users/", backup_serialized)
        self.assertNotIn(self.registered.spans[0].text_preview, backup_serialized)

    def test_persisted_and_public_run_projections_do_not_include_source_text_or_quotes(
        self,
    ):
        provider = RecordingProvider(unsafe_evidence=True)
        runner = self.runner(provider)
        run = runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        persisted = (self.root / "ai_runs.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", persisted)
        self.assertNotIn("/Users/", persisted)
        self.assertNotIn(self.registered.spans[0].text_preview, persisted)

        public = public_ai_run(run)
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertFalse(
            any("text_preview" in source for source in public["input_sources"])
        )
        self.assertFalse(any("quote" in item for item in public["evidence_entries"]))
        self.assertEqual(
            {"output_hash", "top_level_keys", "finding_count", "evidence_span_count"},
            set(public["artifacts"][0]["payload"]),
        )

    def test_registered_source_execution_api_fails_closed_before_runner(self):
        runner = NeverCalledRunner()
        client = TestClient(app)
        with (
            patch("services.api.app.main.source_registry", self.registry),
            patch("services.api.app.main.ai_task_runner", runner),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs/from-sources",
                json=self.request().model_dump(mode="json"),
            )

        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            "monitoring_write_action_unconfigured",
            response.json()["detail"]["code"],
        )
        self.assertFalse(runner.called)

    def test_registered_source_execution_api_requires_server_principal(self):
        runner = NeverCalledRunner()
        client = TestClient(app)
        with patch("services.api.app.main.ai_task_runner", runner):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs/from-sources",
                json=self.request().model_dump(mode="json"),
            )

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )
        self.assertFalse(runner.called)

    def test_ai_result_reads_fail_closed_before_runner_access(self):
        runner = Mock()
        client = TestClient(app)
        paths = (
            f"/api/projects/{PROJECT_ID}/ai-runs",
            f"/api/projects/{PROJECT_ID}/ai-runs/run_missing",
            f"/api/projects/{PROJECT_ID}/ai-runs/run_missing/artifacts",
        )
        with patch("services.api.app.main.ai_task_runner", runner):
            without_principal = [client.get(path) for path in paths]
        with (
            patch("services.api.app.main.ai_task_runner", runner),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            with_principal = [client.get(path) for path in paths]

        for response in without_principal:
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )
        for response in with_principal:
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_read_action_unconfigured",
                response.json()["detail"]["code"],
            )
        runner.list_runs.assert_not_called()
        runner.get.assert_not_called()
        runner.artifacts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
