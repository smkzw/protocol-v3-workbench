# HANDOFF — 0924V2 第一批（无损暂停点）

## 强制接续指令（每个后续 Agent 开工前必须先读完本节）

你接手的是 smkzw/protocol-v3-workbench 医学写作子系统的收尾冲刺。全部用户指令以 0924V2 交付包（/Users/smkzw/Downloads/protocol-v3-0924V2-review.zip，已解包归档至本仓库 runs/requirements_v2_20260919/t17_round16_review_kit_0924v2/ 与 /tmp/protocol_v3_0924v2_review/）为准。工作目录 = 本仓库根。禁止 reset/clean、删除历史、伪造状态；禁止操作用户前台桌面；MTPLX/oMLX 两台本地模型服务器内存互斥（~30GB each / 128GB 机器），不得同时加载，未经用户授权不得启停。

## 一、SOURCE_COMMIT 与 RUNTIME_IDENTITY
- SOURCE_COMMIT：4ea5a6f（重试语义）→ f263768（原因链）→ 本 handoff 提交为最新。审阅基线 ee12adc；0924V2 已落 9 笔新提交（28d03bf/3434809/f36f1d2/fc9bda9/2872868/1ab056a/4ea5a6f/f263768/433ec06+handoff）。
- RUNTIME_IDENTITY：后端 uvicorn 5301（PID 19288+，api-f74375aa2c3f52c7），前端 vite 5186（指纹一致）；重启配方 = 杀 5301/5186 全部监听进程 → python3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 5301，env: PYTHONPATH=services/api:. + WORKBENCH_RUNTIME_DIR/WORKBENCH_AI_SETTINGS_PATH/WORKBENCH_AI_ROLE_SETTINGS_PATH（指向 runs/requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/isolated_runtime/）+ WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED=1 + WORKBENCH_PROTOCOL_V3_WORKFLOW_DB=<同目录>/protocol_v3_product.sqlite；前端 VITE_API_PROXY_TARGET=http://127.0.0.1:5301 + --strictPort。重启后必须验证 /runtime-build.json 与 /api/runtime-readiness 的 build id 一致。
- 模型服务器现场（0925 凌晨）：MTPLX@8002 = 用户已重启，探针 200（8.7s 慢热，reasoning 模式 content 可能为空属 xhigh 推理特性）；oMLX@8001 = 翻译模型 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX 已驻留（探针 0.5s）。两服务器内存互斥，一次只能驻留一个。

## 二、CHANGESET（本批全部已 push）
1. 28d03bf §5族1：忠实度检查器接受中文数量级换算（116 million ↔ 1.16亿；$635 billion ↔ 6350亿）。对称 mantissa/digit 信用 + 小数点宽恕 + 单位零追加宽恕（635↔6350亿）。真实计数漂移（2.50亿）仍拦截。
2. 3434809 §5族2：缩写等价表补 OA/LDN/VA/FDA/MD/PI/SAE/NSAIDs/BPI；检测器噪声词补 NOT/FIRST/MATLAB。R14 证据：中文全称已渲染而表缺条目。
3. f36f1d2 §5族3：时间词（weeks/Wks/周/日/天/月/周岁/岁）出现在数字前 48 字符内任意位置 → 句末 "16." 不再算编号条目。
4. fc9bda9 §3：通用 ingest 端点补服务端 Protocol-only 门（protocol/protocol_sap 之外拒绝，中文指引）。
5. 2872868 §6+§7：writing-ai-candidates 112px 嵌套滚动框移除（14px 全文 pre-wrap）；medicalWritingSafeErrorText 分类 sanitizer + fullDraftDiagnosticRef 展开详情。**教训：模块级正则忘写 const → strict mode 白屏（root 空、构建却通过）——加全局对象必查 const。**
6. 1ab056a §4：preparation scope_sha256 绑定 study_facts_sha256（_material_facts_hash）——研究设计变化即新范围版本。
7. 4ea5a6f §5重试语义：retryFailed 每次点击发新 idempotency key（旧 retryKeyRef 会话缓存导致 create_or_reuse 复用耗尽 job = no-op）。
8. f263768 §7：adapter 两处 transient raise 携带原因链（product_ai_provider_transient: {exc}）——provider transport 元数据设计上安全。

## 三、验收台账（四状态分离）
| 项 | 状态 | 证据 |
|---|---|---|
| §5 三大族修复 | PASSED | 412 后端测试绿（含新增 3 个反例回归：数量级 OK/漂移、缩写全称 OK/真丢、句末周次 vs 真列表）|
| §3 ingest 门 | PASSED | 代码审查 + 现有套件绿；D01 三入口端到端 NOT_RUN（待 K3 批次收敛后随 R16）|
| §4 scope 冻结 | PASSED（实现） | 101 测试绿；S01-S07 端到端 NOT_RUN |
| §6/§7 前端 | PASSED | 构建 + 113 vitest 绿；U01 三档截图入库（t17_round17_uat/）；U02 全 DOM 0 个 112px 框；U03 泄漏扫描 0 命中 |
| T01 三态分账 | 保持 | 38 ready / 164 fidelity_blocked / 26 failed_retryable / 2 excluded |
| T02-T03、T14-T17、S/D 系列 | NOT_RUN/部分 | 见下方 NEXT_GATE |
| FAILED（非回归） | 2 项 | test_document_pipeline_round8 旧契约测试已按 0924V2 重写；剩 4 个 greenfield 存量失败（改动前即存在）|

## 四、当前唯一硬阻断：26 项 failed_retryable 的真实异常源
新恢复尝试（mwjob_5ade4825/b72de0a5，63 秒耗尽 3 次）审计 exc_message 仍为裸 "product_ai_provider_transient"。已查明：
- 该消息由 ChapterTranslationPipelineError(line 698) 从 selected_run.failure_code 携带；
- 修复 f263768 后 adapter 两处 raise 已带原因，且 UpperLayerTransientError.__init__ 经 _safe_failure_code 保留 suffix；
- **但最新尝试未写入任何新 stage run（0 行）→ 失败发生在 upper-layer 执行之前的管道早期（如 item→chapter 分派、adapter factory 构造、或 claim 后的预检）**，该路径的异常被 §7 之前的旧包装吞掉。
- 下批第一步：在 writing_reference_translation_batch.py 的 _process_item/claim 后入口加临时 stderr 诊断（或 traceback.print_exc），跑一次 retry 抓真实栈；找到后修根因（怀疑方向：adapter factory 闭包里 provider 路由身份校验在 oMLX 8001 迁移后不匹配，或模型名 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX 与 route 指纹不一致）。
- 注意：不得用全局 max_attempts 扩张替代根因修复（0924V2 明令）。

## 五、NEXT_GATE（顺序）
1. 26 项根因修复（上述）→ 派发收敛 → 复检 164 项（检查器修复后多大比例转 ready —— 这是 §5 要求的量化证据）。
2. T16/T17 桌面 Office 腿（用户桌面空闲窗口；Word AppleScript cell 寻址有兼容坑：cell N of table 线性索引抛 -1728，改用 find/replace 或 UI 路径）。
3. R16 集中验收：S01-S07（需 K3 收敛后真实 600 项级数据）、D01-D04、T01-T03、U01-U04（截图已入库可复用）、E01-E04；T18 操作负担口径（真实鼠标计数脚本 + 12px/14px computed 字号断言）。
4. 每批报告必须含 SOURCE_COMMIT/RUNTIME_IDENTITY/CHANGESET/PASSED/FAILED/NOT_RUN/证据路径/NEXT_GATE，并在回复正文贴完整 Agent 接续指令。

## 六、红线（不变）
不触碰 live 8910/医学监查/共享 runtime；不删历史 immutable 行；一切提交同步 GitHub；测试全程 UI 黑盒；不经授权不抢占用户桌面、不启停用户模型服务器。
