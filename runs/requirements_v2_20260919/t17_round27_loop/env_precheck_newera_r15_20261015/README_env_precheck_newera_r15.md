# 环境预检与清洁 · 新纪元第15轮证据（本ask第3轮）（2026-10-15 10:23–10:33 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过（实现师侧后端再次换新进程，本轮零重启）
- 前端 5186：HTTP 200；vite pid 81087（延续 r14），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪。
- 后端 5301：**pid 36282（2026-10-15 10:23:24 启动，r14 的 7724 已被换新）**；`/api/health`=ok（runtime_store ok、共享语料 ok）。
- 构建指纹：`/api/runtime-readiness` 自报 `api-be4132cd4b8c8413` = vite `/runtime-build.json` 期望同值（前端 web-60e3543ace22d1c6 同步更新）= 经 5186 代理读同值 **MATCH**（ready=true、missing=[]、independent_ai ready）→ 无漂移，无需重启。
- 编排器 `/api/model-lifecycle/status`：status=ok。预检时 arbiter=null（后端 10:23 刚重启未初始化，历轮 r2/r14 判例同型）、omlx healthy 非驻留、**mtplx resident+owned（pid 73319，编排器自动加载，inflight 0）**——编排器全自动管理未干预；OCR 探针触发切相后 arbiter=omlx、users 0、queue 空、mtplx 按最小驻留正常卸载（reason=process_not_running）。全程无 refused。

## ② 测试者环境隔离 — 通过（附一条归属不明上报）
- ego-browser 空间 8 个，与 r14 完全一致，本子系统遗留空间 **0**：42（入排线）+ 54/60/67/73/80/83/87（R38C–R44C 医学监查并行线，红线不碰）。
- headless：**camoufox 实例 1 个（pid 35969，2026-10-15 10:22:26 启动，headless，0 标签页 idle）**——启动于本次预检首次调用 camofox 工具之前（本线历轮只用 ego-browser），与并行线活跃窗口（后端 10:23 重启同期）重叠，归属不明。按红线保守原则未杀停（若属活跃并行会话杀停有打断风险；idle 不占队列不烧 GPU）；已如实上报待集成人裁定。`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 **0 命中**（无需清理）。

## ④ durable 无卡死任务 — 通过
- isolated_runtime `medical_writing_durable_jobs.sqlite3`（只读）：completed=627 / failed=270 / cancelled=24，**非终态=0**（较 r14 619/266/23 正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` bindings.ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted、enabled）；API 实测（新 5301 进程）roles[ocr] availability=available、ready=true、current_runnable=true。备份 `.pre-ocr-rebind-20260928`/`.pre-ocr-rebind-20261008` 在位。PADDLE key 不存在（历轮裁决，本地路线）——无需改绑/重启，以真实调用取证。
- 实测（全部经产品 API；oMLX pid 99765；590s 客户端超时）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200，11,372ms，mtplx 驻留下切相+冷加载）；RSS 53,728→33,870,528KB；
  2. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 310ms；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **115ms**，RSS 33,873,248KB 稳定 —— 双模型同驻共存无互斥（co_resident=true）。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-15 第15轮节）。
- 证据：`ocr_probe_r15_1.json`、`translation_probe_r15.json`、`ocr_probe_r15_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建；本轮截图恢复可用）
- 基线 `GET /api/projects`（经 5186 代理）→ **187**（r14 收官 185 后自然 +2，作为本轮基线如实记录）。
- ego-browser 空间（用后 finish({keep:[]}) 关闭）：5186 看板「请选择项目（共187个）」UI=API 一致 → 打开「新建项目」→ 对话框「新建研究方案项目」打开，七要素全在（从零开始/导入方案摘要/试验药物/适应症/研究分期/取消/创建并进入）→ 点「取消」→ DIALOG_CLOSED=true、看板复现「共187个」→ `/api/projects` 复验 **187=187 零新建**。r14 的 0×0 视口问题本轮未复现，截图成功（`smoke_new_project_dialog_r15.png`，104KB）。

## 红线自检
未碰 live 8910/8911/医学监查并行进程与并行线 ego 空间（54–87）及归属不明 camoufox 实例（保守不动，已上报）；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002；mtplx 驻留与卸载均为编排器自动行为）；本轮零服务重启零进程杀停；未清库未删历史未 reset（187 基线如实保留；durable 库只读查询）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录。

## 遗留上报（不阻断）
- camoufox headless 实例（pid 35969，10:22:26 起，0 标签页 idle）归属不明：非本线资产（本线只用 ego-browser），疑属并行线活跃窗口，保守未动，待集成人裁定是否清收。
