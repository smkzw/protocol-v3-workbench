# 环境预检与清洁 · 新纪元第10轮证据（2026-10-12 14:27–14:40 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 46211（`lsof -iTCP:5186 -sTCP:LISTEN` 确认，延续第9轮进程未重启），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪。
- 后端 5301：pid 46210（延续第9轮进程，本轮未动）`/api/health`=ok；`/api/runtime-readiness` 自报 `backend_build_id=api-fcd3772c173b7eb7` = vite `/runtime-build.json` 期望 **MATCH**（ready=true），经 5186 代理读同值 ✓。HEAD=d899d198。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检时 arbiter=mtplx 驻留（users 0/0、队列空）；探针后 arbiter=omlx、queue 空、mtplx 按最小驻留正常卸载（全程无 refused）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 2 个：23「入排审核 0.2.0 构建验收」（入排线）、31「R36B 医学监查子系统验收测试」（医学监查线）——**本子系统遗留空间 0**，两个并行线空间全部保留未动。
- headless 进程 0；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- isolated_runtime 库：completed=587 / failed=247 / cancelled=22，**非终态=0**（较第9轮 584/246/22 各增，正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，enabled）；role_revision=104（运行中后端已加载生效）；备份 `.pre-ocr-rebind-20261008` 与 `.pre-ocr-rebind-20260928` 在位。PADDLE key 不存在（历轮穷尽排查+主会话裁决，走本地路线）——绑定目标状态已达成，无新增改绑/重启，以真实调用取证。
- 实测（全部经产品 API；探测开始时仲裁器=mtplx 驻留、队列空；oMLX pid 25352；590s 客户端超时）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200），442,788ms = mtplx→omlx 切相窗口等待+GLM-OCR-bf16 加载单请求内完成，**无阻断无卡死**（切相窗口连续六轮 478/440/421/433/441/443s 量级稳定）；RSS 68,160→33,889,104KB；
  2. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 255ms；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **95ms**，RSS 33,891,040KB 稳定 —— 双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-12 第10轮节）。
- 证据：`ocr_probe_r10_1.json`、`translation_probe_r10.json`、`ocr_probe_r10_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **173**。
- ego-browser 空间 38（用后即关）：5186 项目总看板「请选择项目（共173个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 对话框关闭、`/api/projects` 复验 **173=173 零新建**。冒烟空间已关（复验列表仅剩并行线 23/31）。

## 红线自检
未碰 live 8910/8911/医学监查并行进程；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002；切相等待与 mtplx 卸载均为编排器自动行为）；未清库未删历史未 reset（173 基线如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（23/31）保留。

## 遗留上报（不阻断）
- 无新增。OCR 冷启动切相窗口连续六轮稳定在 7-8 分钟量级（478/440/421/433/441/443s），已在 mem_probe 持续记录供排程参考。
