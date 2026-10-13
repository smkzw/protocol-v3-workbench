# 环境预检与清洁 · 新纪元第13轮证据（2026-10-13 08:00–08:07 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过（本轮零重启）
- 前端 5186：HTTP 200；vite pid 81593（延续 r12 进程），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪；经 5186 代理读 `/api/runtime-readiness` 同值 ✓。
- 后端 5301：pid 96580（r12 02:54 重启后延续）；`/api/health`=ok（runtime_store integrity ok、共享语料 ok、schema 16）；`/api/runtime-readiness` 自报 `api-2d4246c7ddcf6513` = vite `/runtime-build.json` 期望 **MATCH**（ready=true、missing=[]、independent_ai ready）→ 无指纹漂移，本轮无需重启。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检时 arbiter=mtplx（users 0/0、队列空、omlx healthy 非驻留、mtplx process_not_running=最小驻留正常卸载）；探针后 arbiter=omlx resident、users 0/0、queue 空（全程无 refused）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 2 个：42「0.2.0 审定备选与检验衔接验收」（agentDelegatedToUser，用户态，保留）；54「R38C medical monitoring acceptance」（agent，**医学监查并行线空间，红线不碰，保留**）。本子系统遗留空间 0。
- headless 进程 0；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 **0 命中**（无需清理）。

## ④ durable 无卡死任务 — 通过
- isolated_runtime `medical_writing_durable_jobs.sqlite3`（只读查询 durable_mw_jobs）：completed=604 / failed=254 / cancelled=23，**非终态=0**（较 r12 603/253/23 各 +1，正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库未变：`ai_role_bindings.json` ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted、enabled、capability_verified_at=2026-10-12T19:34Z）；API 实测 roles[ocr] availability=available、ready=true、current_runnable=true、role_revision=122。备份 `.pre-ocr-rebind-20260928` 与 `.pre-ocr-rebind-20261008` 在位。PADDLE key 不存在（历轮穷尽排查+主会话裁决，走本地路线）——绑定目标持续达成，本轮无需改绑/重启，OCR 以真实调用取证。
- 实测（全部经产品 API；oMLX pid 25352；590s 客户端超时）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200，8,009ms，页缓存热加载）；RSS 403,392→33,870,160KB；
  2. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 264ms；RSS 33,876,800KB；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **123ms**，RSS 33,876,896KB 稳定 —— 双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-13 第13轮节）。
- 证据：`ocr_probe_r13_1.json`、`translation_probe_r13.txt`、`ocr_probe_r13_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **181**（r12 收官 180 后自然 +1，作为本轮基线如实记录）。
- ego-browser 空间 56（用后即关）：5186 项目总看板「请选择项目（共181个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式/试验药物/适应症/研究分期/取消/创建并进入）→ 点「取消」→ 看板复现「共181个」、`/api/projects` 复验 **181=181 零新建**。冒烟空间已 finish({keep:[]}) 关闭（复验列表仅剩 42 用户态 + 54 医学监查线）。
- 截图：`smoke_new_project_dialog_r13.png`。

## 红线自检
未碰 live 8910/8911/医学监查并行进程与并行线 ego 空间（54）；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；本轮零服务重启零进程杀停；未清库未删历史未 reset（181 基线如实保留；durable 库只读查询）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录。

## 遗留上报（不阻断）
- r26 现场所述 PADDLE 云端 key 缺失的环境侧清偿已由本地绑定路线落地并连续多轮实证；产品侧「下载后解析走 OCR」全链路属测试者任务范围，非本预检项。
