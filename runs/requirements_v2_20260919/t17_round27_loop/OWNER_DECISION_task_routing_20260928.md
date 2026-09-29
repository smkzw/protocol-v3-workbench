# OWNER 决策：写作子系统任务级模型路由（2026-09-28，用户亲授）

## 决策内容（用户原话归纳）

> 竞品分诊、研究设计综合、PICOS 辅导、翻译辅助这些章节应该走 deepseek-v4.1-flash（ollama-cloud）！方案初稿、摘要结构化走 MTPLX。（2026-09-28 用户更正：医学修订也走云端 deepseek-v4.1-flash，本地 MTPLX 只负责方案初稿和摘要结构化）

## 任务类型 → 模型路由表（AiTaskType 精确映射）

| 任务类型（ai_gateway.AiTaskType） | 目标通道 | 实现方式 |
|---|---|---|
| COMPETITIVE_INTELLIGENCE（竞品分诊） | ollama-cloud deepseek-v4.1-flash | 任务级路由 |
| PROTOCOL_DESIGN_SYNTHESIS（研究设计综合） | ollama-cloud deepseek-v4.1-flash | 任务级路由 |
| PICOS_DESIGN_COACH（PICOS 辅导） | ollama-cloud deepseek-v4.1-flash | 任务级路由 |
| PROTOCOL_FULL_DRAFT（方案初稿） | MTPLX（本地 8002, mtplx-flash-next-optimized-speed） | 保持绑定主路 |
| MEDICAL_WRITING_REVISION（医学修订） | ollama-cloud deepseek-v4.1-flash | **维持 owner decision 2026-09-23（修订走云）——用户 2026-09-28 纠正确认** |
| PROTOCOL_SYNOPSIS_STRUCTURING（摘要结构化） | MTPLX（本地 8002） | 保持绑定主路 |
| translation_support 角色（翻译辅助，整体） | ollama-cloud deepseek-v4.1-flash | **配置层已生效（2026-09-28 主会话）** |

## 已完成（主会话 2026-09-28，配置层）

1. `ai_provider_settings.json` 新增 profile `independent_ai__ollama_cloud_dsv41`（provider=ollama-cloud，base_url=https://ollama.com，model=deepseek-v4.1-flash，api_key_env=OLLAMA_CLOUD_API_KEY，transport=openai_compatible，scope=cloud）——照抄 MM 侧实例形态；备份 .pre-ollama-cloud-20260928。
2. 密钥：从 MM 加密凭证库只读解密 OLLAMA_CLOUD_API_KEY，用 MW 本侧 master key 加密写入本 runtime `ai_provider_secrets.json`（键=independent_ai__ollama_cloud_dsv41）；备份 .pre-ollama-cloud-20260928。明文未落盘。
3. `ai_role_bindings.json` translation_support → `independent_ai__ollama_cloud_dsv41`（翻译辅助立即生效）；备份 .pre-task-routing-20260928。

## 待实现（LOOP 修订环节执行，实现师为唯一集成人）

**TASK_TYPE_ROUTE_POLICY**（ai_execution_policy.py，模式照抄 `_capture_revision_cloud_route`）：

```python
# Owner decision 2026-09-28: per-task-type routing（推翻 2026-09-23 revision→cloud）
# 通道解析：
#   "ollama_cloud_dsv41" → settings 中 provider=="ollama-cloud" 且 model=="deepseek-v4.1-flash"
#                          的 enabled profile（independent_ai__ollama_cloud_dsv41，key 在加密store）
#   "mtplx_local"        → 当前绑定主路（independent_ai__mtplx_qwen38_local，8002）
TASK_TYPE_ROUTE_POLICY = {
    AiTaskType.COMPETITIVE_INTELLIGENCE: "ollama_cloud_dsv41",
    AiTaskType.PROTOCOL_DESIGN_SYNTHESIS: "ollama_cloud_dsv41",
    AiTaskType.PICOS_DESIGN_COACH: "ollama_cloud_dsv41",
    AiTaskType.PROTOCOL_FULL_DRAFT: "mtplx_local",
    AiTaskType.MEDICAL_WRITING_REVISION: "ollama_cloud_dsv41",
    AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING: "mtplx_local",
}
```

实现要点：
1. 在 `resolve_internal` / `resolve_registered` 的路由应用点（现 _capture_revision_cloud_route 的 3 处调用位置）改为按 `TASK_TYPE_ROUTE_POLICY.get(task_type)` 应用：命中 ollama_cloud_dsv41 → `_apply_route_profile(ollama_profile, ...)`；命中 mtplx_local → 保持绑定主路（不追加任何覆盖，即撤销 revision→cloud 的强制走云）。
2. `_capture_revision_cloud_route` 保留并对 MEDICAL_WRITING_REVISION 继续生效（修订→云，2026-09-23 决策经用户 2026-09-28 纠正后维持；R11 的 MTPLX 修订质量发现依然成立）——但走云通道应优先 ollama_cloud_dsv41 profile（新策略的通道解析），不再泛取 fallback 链第一个云 profile。
3. `route_identity_snapshot(task_type=...)` 已支持任务级路由体现——确认新策略经该快照进入 durable 身份。
4. `medical_writing_competitor_triage.py` 的 direct route 常量（TRIAGE_MODEL_NAME="deepseek-v4-pro"@api.deepseek.com）不改动——分诊经 gateway（角色绑定+任务级路由）解析，direct 仅历史兼容；但需实测确认 COMPETITIVE_INTELLIGENCE 经新策略确实打到 ollama.com（durable payload ai_route.base_url 验证）。
5. 编排器 `config/model_lifecycle.json`：MTPLX@8002 的 phases 从 ['triage','design'] 改为写作任务语义（如 ['writing']——具体 phase 名以编排器现有枚举为准，ensure("triage") 在分诊走云后不应再拉 MTPLX；如编排器需要新增 phase 枚举，最小改动）。
6. 测试：a) 任务级路由单测（分诊/设计/PICOS→ollama；初稿/修订/摘要→MTPLX 主路；ocr/translation_body 不受影响）；b) 旧 revision→cloud 测试按新决策更新；c) 实测 durable payload 断言 base_url。
7. **生效验证**：重启 5301 后跑一次真实分诊（或探针），durable job 的 ai_route.base_url 应为 https://ollama.com；初稿/修订路由应为 8002。

## 红线提示

- omlx/mtplx 生命周期仍只经编排器；ollama-cloud 是云通道，不涉本地模型生命周期。
- 本决策不改 8910/监查侧任何配置（MM 侧只读了解，未写）。
- 密钥明文未落盘（加密存储）；备份文件含密文不含明文。
