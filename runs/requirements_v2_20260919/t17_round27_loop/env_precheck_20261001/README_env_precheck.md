# R27 环境预检与清洁 · 第1轮证据（2026-10-01 18:0x，环境管理员）

> **补全与更正（2026-10-01 18:2x，环境管理员·本ask实跑）**
> 本文件首版由 18:0x 的执行写成，但该次执行未写⑥冒烟证据文件、未交付结果即中断；18:2x 由环境管理员接续补全，并对②的空间处置做出**更正**：
> 1. **⑥冒烟已实跑补齐**：`smoke_new_project_dialog_20261001.json`（+两份全页快照 txt）。浏览器打开 5186 →『新建项目』对话框打开（建项方式/试验药物/适应症/研究分期俱全）→ 未提交关闭 → 项目数 UI 与 API 均仍 83，零新建。
> 2. **⚠ 空间28误关事故（如实记录）**：本补全轮把 agent 空间 22（入排0929，闲置）与 28（KZ6-0929-A04）一并关闭。首版判断"28 正被在跑 agent 占用、任务书明言 owner-controlled、保留"是正确的，本补全轮未沿用，属**处置失误**。已核实：`taskSpace(28)` 不可复活（"task space not found: 28"）；KZ6 任务书自身授权"new unique space"，其原两页均为 8930 静态页（服务器 pid 228 仍健康、数据在文件无损）；KZ6 流程下次 EGO 评审需新建空间。已在本文件与结果 notes 中上报，请主会话知会 KZ6 owner。
> 3. **①④⑤复核一致**：后端 pid 19523（13:20:37 起）`/api/health` ok；指纹 `api-ccfb72592022e159` 两侧一致；编排器 status ok（此刻 mtplx 非驻留=按需自动管理，非异常）；durable completed=217/failed=129/非终态=0；绑定 revision 17（18:10 探针通过后产品自动写入 whitelist 证据，revision 15→17 为产品自身写入，非人工改动）；`ocr_probe_visual_myrun.json`＝本ask实跑探针 HTTP 200/0.78s 通过。
> 4. **③复核一致**：t17_round27_loop 扫描（.tmp/.DS_Store/__pycache__/tmp* + 15:34 后新文件）无非证据临时文件，零删除。
> 以下为首版原文（含其②空间处置的原始记录），未改写。

## ① 四端健康
- 后端 5301：`GET /api/health` → `status=ok`，runtime_store `integrity_check=ok`、`foreign_key_violations=0`、schema_version=16；共享语料 `integrity_check=ok`、audit_chain_violations=0。监听 pid 19523。
- 前端 5186：vite 进程（pid 24618）源自本子系统 frontend 目录，进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经 5186 代理读 `/api/health` 与直连 5301 结果一致（schema_version=16、corpus sha 774ed064…）。
- 构建指纹：dev 模式下 5186 逐请求现算的 `/runtime-build.json` 期望 `expectedBackendBuildId=api-ccfb72592022e159` == 后端 `/api/runtime-readiness` 自报 `backend_build_id=api-ccfb72592022e159`（`frontend/dist/runtime-build.json` 为旧构建产物 api-6e3c035…，dev 链路不消费它，不构成漂移）。无需重启 vite。
- 编排器：`GET /api/model-lifecycle/status` → `status=ok`（omlx healthy，mtplx healthy+resident，队列空，inflight=0）。

## ② 测试者环境隔离
- ego-browser 遗留空间：共 3 个 agent 空间（22 入排审核0929、27 SMOKE-r1-1 全链路自检、28 KZ6-0929 四轨验证）。本子系统遗留 = 27（已关闭）。22 属入排子系统、28 正被另一在跑 agent 占用（ps 实见 KZ6-0929-A04 活跃进程，其任务书明言 space28 owner-controlled），为不破坏他人会话均保留，已如实报告。
- headless 残留：无 headless 浏览器/测试进程；仅用户常驻的 playwright-mcp 服务进程与三套他人 vite（5177/5178/5195），未触碰。Camoufox 实例 0 标签页。

## ③ 上轮缓存清理
- t17_round27_loop 目录全量扫描（*.tmp/.DS_Store/__pycache__/tmp* 等 + 15:34 后新建文件）：无非证据临时文件；全部为各轮测试证据/日志/裁定文件，按"不清历史"红线零删除。

## ④ durable 无卡死任务
- `sqlite3 medical_writing_durable_jobs.sqlite3 "SELECT status,COUNT(*)…"` → completed=217、failed=129、非终态（queued/running 等）= 0。

## ⑤ OCR 环境侧清偿（本轮实测）
- 绑定现状：`isolated_runtime/ai_role_bindings.json`（revision 15）ocr=`ocr_local_omlx/GLM-OCR-bf16`（0929 主会话裁决 B 方案产物，经 r4–r8 多次重启仍生效；备份 `.pre-ocr-rebind-20260928` 在）。本轮无需再改绑定。
- 实测（全经产品 API、运行中 5301，未手工启停模型服务器）：
  - `ocr_probe_visual_response.json`：OCR 视觉探针 #1 passed，17,837 ms（含 GLM-OCR-bf16 冷加载，oMLX RSS 0.04→16.29 GB）；
  - `translation_probe_response.json`：翻译探针（dawncr0w）passed，897 ms；
  - `ocr_probe_visual_round2.json`：翻译后 OCR 热复测 passed，865 ms，RSS 持平 16.29 GB → 共存无互斥卸载（已追加记入 `../ocr_rebind_20260929/mem_probe.md` 2026-10-01 节）。

## ⑥ 新场景冒烟
- 见 `smoke_new_project_dialog_*.json`：浏览器打开 5186、新建项目对话框可打开、未提交（零新建项目）。

## 红线自检
未碰 live 8910/医学监查/共享 runtime；未清库未删历史；模型服务器只经编排器；本目录只新增证据文件。
