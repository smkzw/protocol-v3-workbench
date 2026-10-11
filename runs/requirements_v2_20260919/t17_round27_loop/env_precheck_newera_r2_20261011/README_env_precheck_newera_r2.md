# 环境预检与清洁 · 新纪元第2轮证据（2026-10-11 12:28–12:40 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 24907（09:28 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`（`ps eww 24907`）✓ 无脚枪。
- 后端 5301：pid 24818（09:28 起，本轮未动）`/api/health`=ok；`/api/runtime-readiness` 自报 `backend_build_id=api-f2b9c4d4635834d3` = vite `/runtime-build.json` 期望值 **MATCH**（ready=true），经 5186 代理读同值 ✓。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检开始时 omlx 健康未驻留、mtplx 健康且驻留（arbiter=mtplx，队列空——R33 并行线场景）；OCR 探针后 arbiter=omlx、omlx 驻留、mtplx 按最小驻留正常卸载（设计内轮换，全程无 refused）。
- HEAD=674e5123（20261010 checkpoint，新纪元 R4 暂停点）；当日两进程均为 09:28 重启，指纹一致无需再重启。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 3 个：2「CI 1007 1011 专用临时验收」（CI 线）、4「R33B 医学监查子系统QA验收」、6「R33-A MY008 PV 验收」（医学监查并行线）——**本子系统（新纪元 LOOP）遗留空间 0**，三个并行线空间全部保留未动。
- headless 进程仅 1 个 = camoufox MCP 浏览器（pid 49742，12:03PM 起，本 harness 基础设施，非测试残留，未动）；remote-debugging 浏览器 0；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- isolated_runtime 库 `SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=553 / failed=236 / cancelled=21，**非终态=0**（较 r1 的 497/221/14 各增，R2-R4 轮正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，enabled）；API 实测 roles[ocr] availability=available、ready=true、role_revision=75（后端 09:28 重启已加载生效）；备份 `.pre-ocr-rebind-20261008` 与 `.pre-ocr-rebind-20260928` 均在位。PADDLE key 不存在（历轮穷尽排查结论，主会话已裁决走本地路线）——本轮无新增改绑/重启动作，绑定目标状态已达成，以真实调用取证。
- 本轮关键验证：**探测开始时仲裁器=mtplx 驻留**（真实并行场景，r2 曾发生 8002 占用阻断、修复后首次在驻留场景复验）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200），258,350ms = mtplx→omlx 切相+GLM-OCR-bf16 冷加载全成本，**无占用阻断**（修复行为实测确认）；
  2. 翻译探针（`POST /api/ai-gateway/probe`，dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 273ms；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **128ms**，RSS 33,839,600→33,841,024KB 稳定 —— 双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 共存与切相结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-11 第2轮节）。
- 证据：`ocr_probe_r2_1.json`、`translation_probe_r2.json`、`ocr_probe_r2_2.json`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **160**（R2-R4 轮测试正常累积）。
- ego-browser 空间 8（前序空间 7 因选择器条件写错误关重建，无副作用）：5186 项目总看板「请选择项目（共160个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 对话框关闭、`/api/projects` 复验 **160=160 零新建**。冒烟空间已关（剩 2/4/6 并行线）。

## 红线自检
未碰 live 8910/8911/医学监查并行进程；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002；mtplx 卸载为编排器最小驻留自动行为）；未清库未删历史未 reset（160 基线如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（2/4/6）保留。

## 遗留上报（不阻断）
- 无新增。首轮上报的 git 工作树漂移事项属集成人职权，本轮未核未动。
