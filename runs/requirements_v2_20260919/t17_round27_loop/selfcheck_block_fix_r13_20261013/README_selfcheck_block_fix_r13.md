# 自检阻断修复 · 新纪元R13（2026-10-13 08:20–09:10 CST，实现师，本ask内实跑）

## 红节点与根因（先证红）
- 红节点：全链路自检在「竞品资料翻译（研究管线 triage-confirm 后翻译阶段）」受阻。
  项目 `proj_user_000bbf0a3331`（入口A建项，节点①绿）：research_pipeline 初跑+竞品分诊完成
  （08:10–08:14 CST），triage-confirm 后翻译批次 3 连败（08:21/08:24/08:32 CST），
  research_pipeline 报「翻译未形成可用关键锚点译文（status=failed，critical_ready=0/4）」。
- 逐段证据（writing_reference.sqlite3 `writing_reference_upper_layer_stage_runs`）：
  2026-10-13 全天 6 条 document_planning 全部 `failed_retryable`，
  failure_code=`product_ai_provider_transient__ai_provider_request_failed_after_bounded_retries__http_429`
  （每条 3 次 transport_retry 全 429）；对照 10-10/10-11/10-12 同路由 4/21/20 条全 succeeded——
  配额在 r12 收官后、r13 自检前耗尽。
- 直接探针（本ask实跑）：`POST https://ollama.com/v1/chat/completions`（translation_support 绑定凭据）
  → HTTP 429 `you (smkfat) have reached your monthly usage limit`——**月度配额耗尽，持久性，非瞬态**，
  重试永不成功。路由归属：`translation_support` 角色 → profile
  `translation_support__independent_ai__ollama_cloud_dsv41`（ollama-cloud/deepseek-v4.1-flash）。

## 修复（按 owner 20261013 裁定的同一切换模式）
主会话同窗口已按 owner 裁定把 `independent_ai__ollama_cloud_dsv41`（提交层路由）切到
cms-router/glm-5.3-flash（备份 `.pre-cmsrouter-switch-20261013`，后端已随其重启，指纹
api-361e634f1c14e56e 与 vite 期望 MATCH）。本节点是**同类受害路由**（新 label 亦明列"翻译辅助"），
按同一模式完成切换，profile_id 与角色绑定不动，仅换三元组：
1. `PUT /api/ai-gateway/profiles/translation_support__independent_ai__ollama_cloud_dsv41`
   → provider=cms-router / model=glm-5.3-flash / base_url=http://127.0.0.1:20128/v1
   （revision 1→2，凭据保留 api_key_configured=true）。
2. `PUT /api/ai-gateway/roles/translation_support`（绑定 model 同步 glm-5.3-flash——
   `role_env` 要求 binding.model==profile.model，不同步则路由解析直接 ValueError）。
- 修复前置验证（本ask实跑）：cms-router glm-5.3-flash 以生产请求形态（thinking enabled +
  reasoning_effort max + response_format json_object + 生产 system prompt）→ HTTP 200，
  响应 model=glm-5.3-flash；```json 围栏由 `ai_gateway._parse_json_content`（ai_gateway.py:2703）
  剥离；持久化上层执行器丢弃 legacy invoke（chapter_translation_pipeline.py:596 `del invoke`），
  模型身份全由服务端路由决定，切模不破坏 stage 契约；AiExecutionPolicyResolver 侧
  `_OLLAMA_CLOUD_DEEPSEEK_V41_FLASH_POLICY` 已被主会话同窗更新为同三元组（127.0.0.1:20128/v1），
  角色环境驱动解析与本切换对齐。
- 备份：`ai_provider_settings.json.pre-ts-cmsrouter-switch-20261013`（runtime 目录内）；
  切换后快照：本目录 `ai_provider_settings.after-ts-switch.json`。
- 生效方式：上层路由每次 stage 调用即时快照（`RuntimeRoutedWritingReferenceUpperLayerExecutionService._snapshot`
  → `role_env` 每次重读盘），无需再次重启后端。

## FAST定向自查（本ask实跑，全部经产品API/真实路由）
1. 角色状态：`GET /api/ai-gateway/roles/status` → translation_support
   provider=cms-router、model=glm-5.3-flash、ready=true、current_runnable=true、无阻断。
2. 原路径复验：`POST .../research-pipeline/resume`（mwjob_1ee0af5fb017a7c0e86a5fed）→
   管线重回 `translating / critical_anchor_translation`。
3. 阻塞节点转绿：新 stage run `wref_ulrun_8c228c7f4979b49c1f955225`
   document_planning **succeeded**，requested=response=glm-5.3-flash，1 次调用零重试
   （对照修复前同节点 3 连 429）。正文翻译推进至 NCT05409183/Prot_000.pdf（1/20 关键锚点起）。
   完整收口状态见下「收尾观测」。

## 收尾观测（本ask内实跑，截至 09:20 CST）
- 修复前同节点：6 条 document_planning 全 429 failed_retryable、critical_ready=0/4、管线死锁。
- 修复后（全部经产品API复验）：
  - document_planning `succeeded ×2`（requested=response=glm-5.3-flash，规划各 1 次调用零重试）；
  - post_hy_mt2_integration_qc：succeeded ×5 / completed_degraded ×1（flash_qc_degraded_hy_mt2_preserved，设计内可接受态）/ failed_terminal ×1（单章QC终态失败属内容级事件，批次可续，非路由故障）；
  - 关键锚点翻译 1/20 → 13/20 持续推进（NCT05409183 完成、NCT06195930 进行中），
    管线离开 `translating` 到 `awaiting_translation_scope`（此前该门即 0/4 死锁点）；
  - 修复后窗口内新后端日志 http_429=0、Traceback=0（近 400KB）。
- 新观察（交账本，非本修复缺陷）：
  1. resume 任务 mwjob_1ee0af5f 于 09:08 报
     「independent AI provider response was not valid: provider_http_error」——语料分析
     （medical_writing_corpus_analysis_ai.py，走 independent_ai=MTPLX 本地直连）在
     oMLX 正文翻译驻留期的串行切换窗口命中 MTPLX HTTP 错误；管线状态机按可恢复暂停处理
     （awaiting_translation_scope + "请处理提示后再次继续"），已完成工作保留。09:16 实测
     oMLX 回驻、锚点翻译恢复 13/20——串行契约按 20261005 裁定工作。下次 resume（测试者或
     下一轮自检）在 MTPLX 就绪时重试该步即可；若再现实为调度问题按红线升级主会话。
  2. 串行切换（oMLX⇄MTPLX 换驻）在翻译中段消耗数分钟墙钟——历轮已知行为，如实记录。
- 后续：下一次全链路自检复验整链（本修复只动了运行时路由环境，未改产品代码）。

## 未做与建议（不阻塞，交账本）
- 代码级"同模型回退链"（上层路由对 429/5xx 自动切换 fallback_chain 内同模型 profile，
  复用 `RuntimeFallbackAiProvider`）：本ask已核实设置库 fallback_chain 现成候选
  （independent_ai__opencode_go_deepseek_v41_flash 同模 deepseek-v4.1-flash，产品头探针 403 仅因
  缺 UA，产品请求头可达）。因主会话正在同仓共享文件上并行落 owner 切换（共享文件单一集成人），
  且 owner 已选定"换路由"为本次配额耗尽的处置模式，未并行实施；作为弹性改进建议立项。
- `_translation_support_provider()`（混合OCR一致性QC 路径）同受本角色环境驱动，随本切换自动生效，未单测。

## 红线自检
未碰 live 8910/8911/医学监查并行线；模型服务器未手工启停（本修复全部经产品 API 与既有 cms-router 网关）；
未清库未删历史未 reset（仅 PUT profile/role 两个运行时配置，revision 正常自增，备份在位）；
未动 immutable 行；未改产品代码（主会话并行改动未触碰）。
