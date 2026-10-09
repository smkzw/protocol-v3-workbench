# 环境预检与清洁 · 新纪元第1轮恢复执行证据（2026-10-08 16:20–16:45 CEST，环境管理员，本ask内实跑）

背景：新纪元r1预检于当日08:00–08:10完成后工作流中断存档（commit 85afb67f，证据见 `../env_precheck_newera_r1_20261008/`）。本ask为恢复执行，按标准全部检查项在本ask内重新实跑取证。

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 9202，进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`（`ps eww 9202`）✓ 无脚枪。
- 后端 5301：pid 43270（08:00 起，本轮未动）`/api/health`=ok；`/api/runtime-readiness` 自报 `backend_build_id=api-b88acb53b5aff176` = vite `/runtime-build.json` 期望 `expectedBackendBuildId=api-b88acb53b5aff176` **MATCH**，ready=true；经 5186 代理读同值 ✓。后端日志 `../backend_5301_round27_restart.log` tail 可见本轮探针流量（16:34），进程与日志对应一致。
- 编排器 `/api/model-lifecycle/status`：status=ok；omlx 健康、arbiter=omlx、users 0/0、queue 空；mtplx owned=false reason=process_not_running（最小驻留正常卸载，release_unconfirmed=false，设计内轮换）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间：本线遗留空间 161「SMOKE-r1-1 full chain check」（tab=5186，中断run遗留）已 `finish({keep:[]})` 关闭；冒烟空间 165 用后即关。保留并行线空间 147（入排）/157/162/163/164（医学监查，其中164为本轮期间并行线新建）。
- headless 进程 0；remote-debugging 浏览器进程 0；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp 扫描 0 命中（find 实跑）。证据目录与后端重启日志为历史证据，保留不清。

## ④ durable 无卡死任务 — 通过
- 运行时库（后端实际 WORKBENCH_RUNTIME_DIR=wp6_0922v2_20260922/real_http_acceptance/isolated_runtime）：`SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=497 / failed=221 / cancelled=14，非终态=0，无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` ocr 角色 = `ocr_local_omlx/GLM-OCR-bf16`（capability_status=specialized_whitelisted）；API 实测 roles[ocr] availability=available、ready=true、role_revision=63；备份 `ai_role_bindings.json.pre-ocr-rebind-20261008` 在位。PADDLE key 仍不存在（历轮穷尽排查结论）。后端 08:00 重启（pid 43270）已使绑定生效——本轮目标状态已达成，故未做冗余改绑/重启；以真实调用取证。
- 实测（全经产品 API，oMLX pid 2264）：
  1. OCR 视觉探针 #1（`POST /api/ai-gateway/roles/ocr/probe-visual`）→ HTTP 200，visual_probe.passed=true，3,228ms，RSS 451,200→2,653,952KB（加载中）；
  2. 翻译探针（`POST /api/ai-gateway/probe`，translation_body_local_omlx / dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed，6,746ms，RSS 33,958,592KB（两模型同驻）；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **126ms**，RSS 33,959,376KB —— 翻译加载后 OCR 仍亚秒热响应=双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 共存结论已追记 `../ocr_rebind_20260929/mem_probe.md` 新纪元第1轮恢复执行节。
- 证据：`ocr_probe_resume_1.json`、`translation_probe_resume.json`、`ocr_probe_resume_2.json`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ 148（晨间147之后+1，为中断run SMOKE 全链检查所建，按红线不清库保留）。
- ego-browser 空间165（用后即关）：5186 打开项目总看板「请选择项目（共148个）」（UI=API）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 对话框关闭、`/api/projects` 复验 148 = **零新建**。
- 冒烟过程快照要点记录于本README（空间已按规范关闭，未保留浏览器现场）。

## 红线自检
未碰 live 8910/8911/医学监查（pid 20020/20063/20086 等并行线进程未动）；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；未清库未删历史未 reset（148基线含SMOKE项目如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（147/157/162/163/164）保留。

## 遗留上报（不阻断）
- git 未提交漂移（集成人职权）：服务代码 `services/api/app/ai_task_runner.py`、`services/api/app/medical_writing_synopsis_import.py`（自10-04/10-05遗留，与晨间存档一致）；较晨间存档新增测试侧 M：`tests/_composite_pipeline_fixture.py`、`tests/acceptance/test_model_lifecycle_orchestrator.py`、`tests/test_mw_project_create_double_submit_r27.py`（疑为中断run自检修订或并行线所为，本管理员未动）。本轮指纹判定按盘上源码树现算两侧一致，不受影响。
- 编排器 local_inventory_errors 显示 `independent_ai__mtplx_qwen38_local` models 端点 transport_error（8002 未驻留时库存探测失败的正常表现，任务需要时编排器自动拉起）。
