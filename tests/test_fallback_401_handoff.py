# -*- coding: utf-8 -*-
"""SMOKE-r2-2 ⑦（R27 收敛修订）反例：401 耗尽后不走回退链。

现场：airun_20261001023257（修订，ollama-cloud）在 401 已入有界重试集
后仍三连 401 失败——主路重试只能熬过秒级抖动，熬不过分钟级上游鉴权窗
口；而回退判定 AI_FALLBACK_HTTP_STATUSES 不含 401，_fallback_reason 返
回空串，opencode-go（同模型异载体，早期轮次修订实证可用）从未被尝试，
整个任务一票否决。修后契约：401 耗尽后 fallback_reason 返回
provider_http_error:401，回退链接管；其他 4xx（如 400 参数错）依旧不回
退（客户端错误重试/换路由都无意义）。
"""
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import (
    AiTaskArtifact,
    AiTaskRun,
    AiTaskRunStatus,
    AiTaskSourceRef,
)
from services.api.app.ai_task_runner import (
    AI_FALLBACK_HTTP_STATUSES,
    AiTaskRunner,
)


def _failed_run_with_status(http_status: int) -> AiTaskRun:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return AiTaskRun(
        run_id="airun_fallback_401",
        project_id="proj_fallback_401",
        module="medical_writing",
        task_type="medical_writing_revision",
        purpose="修订候选生成",
        status=AiTaskRunStatus.FAILED,
        provider="ollama-cloud",
        model_name="deepseek-v4.1-flash",
        ai_gateway_status="configured",
        prompt_version="medical_writing_revision_v1_4",
        created_at=now,
        updated_at=now,
        error_message=f"AI provider request failed after bounded retries: HTTP {http_status}",
        artifacts=[
            AiTaskArtifact(
                artifact_id="artifact_fallback_diagnostics",
                artifact_type="provider_failure_diagnostics",
                payload={
                    "diagnostics": {
                        "failure_code": "provider_http_error",
                        "http_status": http_status,
                    }
                },
                validation_errors=[f"HTTP {http_status}"],
            )
        ],
    )


_fallback_reason = AiTaskRunner._fallback_reason


class FallbackStatusTests(unittest.TestCase):
    def test_401_exhaustion_triggers_fallback_reason(self):
        self.assertIn(401, AI_FALLBACK_HTTP_STATUSES)
        run = _failed_run_with_status(401)
        self.assertEqual(
            "provider_http_error:401",
            _fallback_reason(run),
            "401 耗尽必须触发回退链（opencode-go 同模型异载体）",
        )

    def test_400_client_error_still_does_not_fallback(self):
        self.assertNotIn(400, AI_FALLBACK_HTTP_STATUSES)
        run = _failed_run_with_status(400)
        self.assertEqual("", _fallback_reason(run))

    def test_transport_error_still_triggers_fallback(self):
        run = _failed_run_with_status(429)
        run.artifacts[0].payload["diagnostics"] = {
            "failure_code": "provider_transport_error",
            "exception_type": "RemoteDisconnected",
        }
        self.assertEqual(
            "provider_transport_error", _fallback_reason(run)
        )


class FallbackProfileIdentityTests(unittest.TestCase):
    """SMOKE-r2-2 ⑦实锤反例：回退链解析的档案撕裂。

    现场（airun_20261001023257，fallback_depth=1）：route_profile_id=
    opencode_go 但 base_url=ollama.com、provider=ollama-cloud——回退链
    resolve_internal_for_profile 构造的静态解析器被任务级路由捕获再次
    覆盖，opencode-go 档案被撕成 ollama 端点+OPENCODE 密钥 → 401×3。
    修后契约：静态（回退链）解析器身份完整冻结——base_url、provider、
    密钥环境三者同源且等于指定 profile；任务级路由表只在动态解析器
    （绑定主路）上生效。
    """

    def test_fallback_profile_resolution_keeps_designated_identity(self):
        """生产入口 resolve_internal_for_profile：整个解析必须与指定
        profile 同源（档案/端点/密钥环境/身份哈希四位一体）——即便运行时
        设置里存在任务级路由表指定的 ollama 云档（与生产 isolated_runtime
        同构），静态回退解析也不得被覆盖。"""
        import tempfile as _tempfile

        from packages.contracts.workbench_contracts import AiTaskRequest
        from services.api.app.ai_execution_policy import (
            AiExecutionPolicyResolver,
        )
        from services.api.app.ai_runtime_settings import (
            AiFallbackRoute,
            AiProviderProfile,
            AiRuntimeSettingsStore,
        )

        with _tempfile.TemporaryDirectory() as tmp:
            store = AiRuntimeSettingsStore(Path(tmp) / "settings.json")
            # 与生产 isolated_runtime 同构：绑定主路=本地 MTPLX（active），
            # 回退链=opencode 云，任务级路由表指定 ollama 云档
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
            store.set_fallback_chain(
                [AiFallbackRoute(profile_id=opencode.profile_id)]
            )
            profile = opencode
            from unittest.mock import patch as _patch

            with _patch(
                "services.api.app.ai_execution_policy.runtime_ai_settings_store",
                return_value=store,
            ):
                resolver = AiExecutionPolicyResolver()
                request = AiTaskRequest(
                    module="medical_writing",
                    task_type="medical_writing_revision",
                    prompt_version="medical_writing_revision_v1_4",
                    allowed_sources=[
                        AiTaskSourceRef(
                            source_id="src_fb",
                            source_type="protocol_docx_paragraph_selection",
                            title="章节",
                            locator="docx:p1",
                            text_preview="正文。",
                            project_id="proj_fb",
                            module="medical_writing",
                        )
                    ],
                    user_instruction="改写",
                    task_context={
                        "revision_intent": "medical_writing_revision",
                        "intent_label": "改写",
                        "directional_goal": "规范表达。",
                        "preservation_rules": ["不得新增事实。"],
                        "candidate_count": 3,
                        "candidate_blueprints": [
                            "标准版",
                            "精炼版",
                            "保守版",
                        ],
                    },
                )
                resolution = resolver.resolve_internal_for_profile(
                    "proj_fb", request, profile
                )
        self.assertEqual(
            "https://opencode.ai/zen/go/v1",
            resolution.base_url,
            "回退解析的 base_url 必须保持 opencode-go，不得被任务级路由"
            "覆盖成 ollama.com（档案撕裂=用错密钥=401）",
        )
        self.assertEqual("opencode-go", resolution.provider_name)
        self.assertEqual(
            "deepseek-v4.1-flash", resolution.model_name
        )
        self.assertEqual(
            "independent_ai__opencode_go_deepseek_v41_flash",
            resolution.route_profile_id,
        )
        self.assertEqual(
            "OPENCODE_API_KEY",
            resolution.route_api_key_env,
            "密钥环境必须与档案同源",
        )


if __name__ == "__main__":
    unittest.main()
