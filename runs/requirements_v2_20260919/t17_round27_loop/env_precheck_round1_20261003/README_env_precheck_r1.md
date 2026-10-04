# 环境预检与清洁 · 第1轮证据（2026-10-03 18:10–18:20 CEST，环境管理员，本ask内实跑）

前置说明：今日早间（05:04–05:06 CEST，即 env_precheck_20261003/ 内"第2轮"）已做过一轮预检；
本轮为**新测试循环第1轮**，六项检查全部在本ask内重新实跑，不复用早间结论。

## ① 四端健康
- 前端 5186：HTTP 200；vite pid 28147（11:32:47 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`，启动参数含 `--host 127.0.0.1 --port 5186 --strictPort`；经 5186 代理读 `/api/health`=ok 与直连一致。
- 后端 5301：pid 28117（11:32:40 起），`GET /api/health`→status=ok（runtime_store integrity ok、FK违规0、schema 16；共享语料 integrity ok、审计链违规0）。
- 构建指纹：5186 `/runtime-build.json`（vite 中间件逐请求现算，见 frontend/vite.config.mjs:69）期望 `api-6197ca341710c7b1` == 后端 `/api/runtime-readiness` 自报 `api-6197ca341710c7b1`，且 ready=true、missing_capabilities=[]。18:09 新提交 95c5493 仅新增 runs 日志、未动源码（`git show --stat` 核实），运行中后端与当前源一致，无需重启。HEAD=95c5493（2026-10-03 18:09，≥f72fa95）。
- 编排器：`GET /api/model-lifecycle/status`→status=ok；omlx healthy+resident（8001 在听，GLM-OCR-bf16/翻译模型等8个模型在列）；mtplx healthy=false 非驻留（idle 回收态，owned=false/process_not_running，仲裁队列空 inflight=0）——编排器全自动管理的既知设计行为（与 mem_probe.md 09-29 节记录一致），非异常。

## ② 测试者环境隔离
- ego-browser 清点：3 个 agent 遗留空间（id 12 "CI R24 continued desktop acceptance"、id 17 "入排审核1001V1接续"、id 18 "SMOKE-r1-1 全链路自检"）→ 已逐一 `finish({keep:[]})` 关闭，复核清零。
- 用户自有空间：清点时已为 0（用户自行关闭，无需保留处置）。
- headless 残留：`ps aux | grep -i headless` → 0；无 camoufox/chrome 测试残留进程。
- 【如实上报】预检期间新出现空间 id 19 "入排审核1001续作"（agent，初次清点时不存在，系并行会话正在活动的空间）——非本轮遗留，未关闭，未触碰。

## ③ 上轮缓存清理
- `find t17_round27_loop`（.DS_Store/*.tmp/*.pyc/__pycache__/*~/*.swp）→ 0 命中，**零删除**（守不清历史红线；目录内全部为证据/日志/规格档）。

## ④ durable 无卡死任务
- 运行中 5301 的 WORKBENCH_RUNTIME_DIR（wp6_0922v2_20260922/real_http_acceptance/isolated_runtime）`medical_writing_durable_jobs.sqlite3` 表 durable_mw_jobs：completed=263 / failed=144 / cancelled=1 / **非终态=0**。

## ⑤ OCR 环境侧清偿（复核 + 实测）
- 缺口重读：retest_r26.md:68/75——语料解析报 "OCR API Key is not configured for the Paddle provider (0/4)"，R26-QA P0-1 根因。
- 密钥复核：`grep -c PADDLE ~/.config/cms-medical-workbench/ai-runtime.env`→0；运行中 5301 进程环境 PADDLE 命中 0——key 仍不存在，维持主会话裁决路线（ocr→ocr_local_omlx）。
- 绑定核验：`ai_role_bindings.json` revision 19，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，capability_status=specialized_whitelisted）；改绑备份 `ai_role_bindings.json.pre-ocr-rebind-20260928` 仍在。绑定早于运行中 5301 进程启动（11:32），随启动已生效，本轮无需重启。
- 实测（经产品 API、真实读图推理）：
  1. OCR 视觉探针 #1：HTTP 200，`visual_probe={passed:true, profile:ocr_local_omlx, model:GLM-OCR-bf16, provider:omlx, elapsed_ms:165}`（模型热态，准确读出校验码，否则端点按 main.py:4008 报 502）→ `ocr_probe_visual_r1.json`
  2. 翻译探针（translation_body_local_omlx/dawncr0w）：HTTP 200，passed=true，structured={"status":"ok"}，352ms → `translation_probe_r1.json`
  3. OCR 视觉探针 #2（翻译后热复测）：passed=true，162ms → `ocr_probe_visual_r1_round2.json`
- 共存实测：8001 `/v1/models` 同时列出 GLM-OCR-bf16 与 dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX；oMLX RSS 全程 ~32.3 GB 稳定；已按裁记入 `../ocr_rebind_20260929/mem_probe.md`（2026-10-03 节）。
- 未改任何产品代码（纯环境侧）。

## ⑥ 新场景冒烟（ego-browser 真实浏览器，space 20，用后即关）
- 基线：`GET /api/projects`→91。
- 打开 http://127.0.0.1:5186 → 标题"康哲 AI 医学经理工作台"，项目选择器显示"请选择项目（共91个）"（UI=API 一致）→ `smoke_r1_home_snapshot.txt`
- 点击"新建项目"（ref=12）→ 对话框"新建医学写作项目"打开，建项方式/试验药物/适应症/研究分期四要素俱全 → `smoke_r1_dialog_open_snapshot.txt`
- 点击"取消"（ref=22，不提交）→ 对话框关闭（关闭后快照"新建医学写作项目"0 命中）→ `smoke_r1_dialog_closed_snapshot.txt`
- 复核：UI 仍"共91个"、API 仍 91，零新建。空间 20 已 finish 关闭。

## 红线自检
未碰 live 8910 / 医学监查 / 共享 runtime（本轮 8910 未探测、无需触碰）；模型服务器只经编排器（全部探针走产品 API）；未清库未删历史（缓存清理零删除）；未改产品代码；仅关闭 agent 遗留空间，未动用户空间与并行活动空间（id 19）。
