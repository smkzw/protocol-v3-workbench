# 复测报告 Round25-Loop · 第1次复测（retest_round1）

- 复测人：复测协调员（经 ego-browser 真实浏览器操作 + 真实并发压测，未直调 API 推进任何测试状态）
- 复测时间：2026-09-28 14:17–14:55
- 前端：http://127.0.0.1:5186（Vite dev，PID 26573，源码级最新）
- 仓库：`implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`，HEAD=d9d70a3 + 未提交修复（`git diff --stat`：19 文件，+1075/−122；新增 test_model_phase_arbiter.py、test_synopsis_route_freeze_chain.py、runtimeReadiness.test.js、prefillDestination.test.jsx）

## 结论摘要

| # | 上轮缺陷 | 本轮修复内容 | 复测结论 |
|---|---|---|---|
| 1 | P0 前后端构建不一致死锁写作工作区（T1/T2/T3） | AGG25-P0-1：构建漂移降级为告警横幅 | ✅ **已修复（浏览器实测）** |
| 2 | P0 入口B导入解析失败死循环（T2 P0-1、T4-01/08/09） | AGG25-P0-2①/P1-1 路由冻结链+结构化失败 | ❌ **未修复且新增P0回归**（chunk/recovery/resume 路径 AttributeError 崩溃） |
| 3 | 并发仲裁硬性约束（排队+最小驻留窗+队列超时；P0-A/P1-C/P1-D/P1-7/P1-8） | PhaseArbiter + 网关仲裁括号 + 审计 | ✅ **机制生效（压测+审计）**，附1条P2观察 |
| 4 | P2/P1 刷新后项目选择丢失/误选他人项目（T3-P2、T4-06） | AGG25-P1-6 空态+sessionStorage持久化 | ✅ **修复生效**，残留1个小缺口（P2） |
| 5 | P1 product-profile/CT.gov 卡片微调按钮无效（AGG25-P1-5） | prefillDestination 前缀回退映射 | ✅ **已修复（真实bundle验证+单测）** |
| 6 | 事实采集 provider 不可用误报 409（AGG25-P1-4） | 503 provider_unavailable + 输入保留 | ✅ 代码+单测验证；UI现场触发未复现（需破坏共享AI配置，不做） |

**allPass = false**：缺陷2 未收敛（P0，入口B仍走不通）；"五场景全部导出Word"未达成；存在开放P0。

---

## 一、重启与指纹核对（①）

重启前记录：
```
build: api-34b93403aa68bba4 | ready: True        # 10:14 启动的旧进程（不含13:38-14:09的修复）
GET /api/model-lifecycle/status → HTTP 404        # P1-7 新端点不存在 ⇒ 旧代码实锤
```
操作：`kill 13193`（旧5301）→ 执行 `runs/requirements_v2_20260919/t17_round26_loop/start_5301_round26.sh`（env 五件套照抄 round22/23 配方，日志追加至 round26 log）。

重启后：
```
build: api-7830c5238797d6e7 | ready: True
GET /api/model-lifecycle/status → 200 {"status":"ok","servers":{...},"arbiter":...}   # P1-7 端点生效
```
指纹已变更且新端点在线，确认本轮产品代码已加载。未触碰 live 8910（PID 12677 全程未动）。

## 二、每条缺陷的浏览器验证（用户视角）

### 1. P0 版本门禁死锁 → ✅ 已修复
- 操作：总看板 → 新建项目 → 从零开始 → 填"R1-SGLT2口服抑制剂 / 2型糖尿病肾病 / III期" → 创建并进入写作。
- 结果：项目建成（MW-III-8AE37D1A），**写作工作区直接放行**，顶部出现黄色告警条（非阻断）：
  `⚠ 前后端构建不一致（期望 api-34b93403aa68bba4，当前 api-7830c5238797d6e7），可能缺少最新修复，建议刷新页面或同步前后端`
- 证据：`retest_round1_shots/01_写作工作区放行_告警横幅.png`；代码 `frontend/src/runtimeReadiness.js:20-31`（reasons→warnings）、`frontend/src/App.jsx:15451-15462`（RuntimeBuildWarningsBanner）、`App.jsx:16370-16381`（门禁改横幅）；单测 runtimeReadiness.test.js 3/3 通过。

### 2. 入口B 导入方案摘要 → ❌ 未修复，且新增 P0 回归
- 操作：新建项目 → 导入方案摘要 → 上传 NSCLC 摘要 docx（40KB，与上轮T2同款材料）→ 点"导入并提取"。
- 实测结果（约5秒内）：
  - 红条：`chunk 0 AI call failed: 'MedicalWritingSynopsisImportService' object has no attribute '_assert_current_route_matches'`（**内部 Python 异常直接裸露给用户**）
  - 点界面"继续处理"→ `请求失败（500）`（仍是死路）
- 根因（代码定位，未修复仅记录）：本轮把 `_assert_current_route_matches` 重构为 `_reconcile_route`，但只改了主同步路径 `services/api/app/medical_writing_synopsis_import.py:590`；三处调用点没改——
  - `:1724` chunk worker 路径（本次浏览器命中的就是它，报错在 `:1737` 被包成 "chunk N AI call failed"）
  - `:2205` recovery 路径
  - `:2695` resume_job 路径（后端 traceback 坐实：`main.py:7630 resume_file_first_synopsis_project_intake → medical_writing_synopsis_import.py:2695 AttributeError → HTTP 500`，见 `t17_round26_loop/backend_5301_round26_restart.log` 尾部）
  - 另外 `:1727` 把字符串 hash 传给新签名 `_validate_ai_run_route(run, frozen_snapshot: dict)`，`_frozen_route_hashes` 对非 dict 返回空集合 ⇒ **即使补回方法名，chunk 路径仍会路由校验失败**——重构未完成。
- 对比上轮：上轮报"模型地址不在已批准列表/继续处理循环"，本轮直接崩溃，且 P1-1 的结构化 failure_code（local_model_offline 等）在真实入口B上完全没机会生效（AttributeError 归类为 import_failed → 裸露原文）。
- 测试盲区：`tests/test_synopsis_route_freeze_chain.py`（本轮新增）通过，但只覆盖主同步路径，未覆盖 chunk worker / recovery / resume 三条路径。
- 上轮 T4-08（v2 文件提取挂起超10分钟）本轮未被触发：现在同一入口在秒级即崩溃，挂起问题被崩溃掩盖，修复与否无法判定。

### 3. 并发仲裁（硬性约束）→ ✅ 机制生效（详见第三章压测）
- `/api/model-lifecycle/status`（AGG25 P1-7）实时可见 `current / users / queue`：压测中 `current=mtplx, users={mtplx:2}, queue=[translation@omlx]` —— 跨阶段请求 **FIFO 排队而不是报错**（上轮基线是 502 拒绝）。
- 审计（`t17_round21_model_scheduler/actions.log`）：14:26:00 `arbiter/switch phase_switch triage@mtplx`（granted）+ `launch_detached` + `ensure_complete A18 verified 16.65s`；14:38:00 `arbiter/queue queue_enter translation@omlx queued at position 1`。重启以来 rollback / queue_timeout / switch_retry 计数 = 0。
- 非受管端点旁路审计生效：14:35:37 多条 `unarbitrated_managed_dispatch … allowed: endpoint not managed`（AGG25-P0-2③）。

### 4. 项目选择（AGG25-P1-6）→ ✅ 修复生效，残留一小缺口
- 新会话打开看板：显示空态"暂无项目"，**不再静默选中他人的项目**（上轮 T2/T4 默认落在他人项目并可触发503降级）。
- 监查深链 `/monitoring?project_id=proj_user_14434296d068` → 项目正确选中，`sessionStorage["workbench.monitoring.projectId"]` 写入；随后普通 `/` 刷新 → **选择恢复**（R1 项目仍在下拉框选中位）。
- 残留缺口（P2）：经顶部下拉**手动**选择项目不落盘（`App.jsx` 仅在项目列表加载 effect `:15776` 里持久化，`requestProjectChange :15727` 不持久化），该路径刷新后回落空态。安全（不会误选他人），但"记住我的项目"承诺未覆盖此路径。建议实现师把 `persistMonitoringProjectId` 挂进 `requestProjectChange`。

### 5. 预填映射（AGG25-P1-5）→ ✅ 已修复
- 在真实页面上下文动态加载 Vite 提供的模块并调用：
  `prefillDestination("framing.product_profile.*") / ("framing.clinicaltrials.*") → {stage:"framing",group:"identity"}`（旧代码返回 null ⇒ 点击无效）；未知路径仍返回 null（正确兜底）。
- 单测 `MedicalWritingAuthoringJourneySetup.prefillDestination.test.jsx` 3/3 通过。

### 6. 事实采集 503（AGG25-P1-4）→ ✅ 代码+单测验证（UI现场触发未复现）
- `main.py:6954-6963` 新增 `MedicalWritingFactIntakeProviderUnavailableError → HTTP 503 {"code":"provider_unavailable"}`；`medical_writing_fact_intake.py:1283-1293` 不再当 409 冲突；前端 `MedicalWritingAuthoringJourneySetup.jsx:1596-1613` 保留已输入内容可重试。
- 单测：`tests/test_medical_writing_fact_intake.py:1210`（broken provider → ProviderUnavailableError），已包含在本次 152 通过内。
- 说明：现场复现需要人为弄坏共享 AI 配置（红线禁止），故 UI 端到端触发未执行，如实记录。

## 三、并发压测复跑（②，10分钟双负载）

- 脚本：`retest_round1_artifacts/concurrency_drill.py`（与 round26 同配方：负载甲=translation_body_local_omlx 探针、负载乙=independent_ai__mtplx_qwen38_local 探针，经产品入口 `/api/ai-gateway/probe`，600s，每5s采样驻留）。
- 额外真实负载：压测期间我创建的 R1 项目正在跑语料竞品分诊（MTPLX 生成 76s/批，见 mtplx_server.log 生成事件），构成真实的第三路同相负载——更贴近"并发用户分别命中两个阶段"。
- 结果（`retest_round1_artifacts/concurrency_drill_summary.json` + events.jsonl）：
  - triage：9/9 全部 200 且 passed（单个 44–84s，因串行调度排队在 76s 大生成之后）；
  - translation：1 个请求排队 900s 后被**客户端**超时（status -1 TimeoutError）；期间仲裁器未报错，其 1800s `phase_queue_timeout` 阀值未到；
  - **双载 = 0**：121/121 采样中 8001 上唯一 loaded 模型是 `MarkItDown`（oMLX 文档转换小助手，非受管翻译模型）；翻译大模型 `dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX` 全程 `loaded=false`（压测后复核一致）。**翻译模型与 VLM 全程未同时驻留**。
  - **过载/仲裁错误 = 0**：无 502 拒绝（上轮基线：triage 1请求 502 "omlx has in-flight work"）、无 409、无 phase_queue_timeout、无 rollback。
- P2 观察（如实记录，不算过载错误）：持有方被持续同相真实负载占满时，跨阶段队头会长时间等待（本次 900s 客户端先行放弃；服务端排队项残留至 1800s 阀值由仲裁器显式超时）。机制符合"宁可排队、不可双载"红线，但排队期间写作 UI 没有任何"你在排队/第几位"的提示——P1-7 的状态端点已具备，前端未接。另：客户端断开后服务端排队项仍占位至超时，属已知代价，建议实现师评估对客户端断开的感知取消。

## 四、回归抽查（③：上轮PASS环节）

- 抽查对象：上轮 T5 PASS 的关键环节"写作工作区进入 + 研究框架引导"（T5 截图 02_写作工作区_版本门放行_研究框架引导）。
- 本轮实测：R1 项目进入写作模块后，研究设计引导完整呈现（01 研究框架 / 02 PICOS设计 / 03 语料准备），五大模块（研究设计/干预与合并/结局与终点/研究人群/产品画像/执行与统计）正常渲染，语料管道真实运行（锁定 1636 项候选、竞品文献 15/49 分诊经 MTPLX 成功生成）。**未发现回归**。截图 `04_写作模块_模块矩阵与语料状态.png`。

## 五、单测佐证（本轮新增/改动文件）

- 后端：`python3 -m pytest tests/acceptance/test_model_phase_arbiter.py tests/test_synopsis_route_freeze_chain.py tests/acceptance/test_model_lifecycle_orchestrator.py tests/test_ai_gateway.py tests/test_medical_writing_fact_intake.py -q` → **152 passed, 17 subtests passed**（含仲裁 r1 排队/交替、r3 队列超时显式报错、r7 网关透传 phase_queue_timeout）。
- 前端（按项目配方 `vitest --environment jsdom` / `node --test`）：runtimeReadiness 3✓ + SynopsisProjectIntake 10✓ + prefillDestination 3✓ + medicalMonitoringRouteState 56✓。
- 注： SynopsisProjectIntake 三个用例（路由政策降级文案/继续处理按钮保留/StrictMode 重放）在单测中通过，但真实系统里 chunk 路径的 AttributeError 让这些用户体验改进无从触达——再次印证缺陷2是后端路径回归，不是前端文案问题。

## 六、收敛判定与下一步

- 五场景全部导出 Word：**未达成**（入口B 建项被缺陷2挡死；从零开始链路本轮只按抽查深度走到研究框架/语料阶段）。
- 开放 P0/P1：**存在 1 个开放 P0（缺陷2）**，另有 P2 两条（排队无UI提示、手动选择不落盘）。
- 下一步（给实现师）：补完 `medical_writing_synopsis_import.py` 重构——`:1724/:2205/:2695` 三处改用 `_reconcile_route` 语义、`:1727` 传 `route_snapshot` 而非 hash 字符串，并把 chunk/recovery/resume 三条路径纳入 `test_synopsis_route_freeze_chain.py`；然后按配方重启 5301 再复测入口B。

## 证据文件清单（`runs/requirements_v2_20260919/t17_round25_loop/`）

- `retest_round1_shots/01_写作工作区放行_告警横幅.png`（P0-1修复证据）
- `retest_round1_shots/02_导入提取_启动.png`、`03_继续处理_仍失败_AttributeError.png`（缺陷2证据）
- `retest_round1_shots/04_写作模块_模块矩阵与语料状态.png`（回归抽查）
- `retest_round1_artifacts/concurrency_drill_summary.json`、`concurrency_drill_events.jsonl`、`drill_stdout.log`（压测）
- `retest_round1_artifacts/restart_5301_used.sh`（本轮重启配方副本）
- 审计：`t17_round21_model_scheduler/actions.log`（14:26 switch / 14:38 queue_enter / 0 rollback / 0 timeout）
- 后端崩溃 traceback：`t17_round26_loop/backend_5301_round26_restart.log` 尾部（resume_job → :2695 AttributeError）
