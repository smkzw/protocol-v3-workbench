# 环境预检与清洁 · 新纪元第2轮证据（2026-10-09 04:48–04:55 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 44285（10-09 01:46 起，旧9202已由实现师侧正常重启替换），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓（`ps eww 44285`）。
- 后端 5301：pid 44173（10-09 01:45 起）`/api/health`=ok；`/api/runtime-readiness` 自报 `api-70177dabe5ffaf25` = vite `/runtime-build.json` 期望 **MATCH**，ready=true。后端与vite均为01:45/01:46新进程，指纹一致无漂移。
- 编排器 `/api/model-lifecycle/status`：status=ok；arbiter=mtplx、users 0/0、queue空；mtplx owned=true 但 inflight=0、draining=false（最小驻留窗口内空闲，编排器将按策略自动释放，设计内行为）；omlx healthy=true。
- git HEAD=1d191516 ≥ 9339a0c2 ✓。

## ② 测试者环境隔离 — 通过
- ego-browser 空间仅剩 147（入排）/157（医学监查）两个并行线空间 → 保留；本线遗留 0（第1轮的162/163/164已被并行线自行关闭）；冒烟空间178用后即关。
- headless 匹配进程 1 个 = camoufox MCP（`/Users/smkzw/Library/Caches/camoufox/...` pid 61302，10-09 04:41 起）为 harness 常驻 MCP 基础设施，非测试残留，未动。`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp 扫描 0 命中（find 实跑）。新增 r1-A/r1-B/r1-C、retest_r1_newera_shots/、retest_r1_newera_material/ 为新纪元第1轮测试证据目录，保留。

## ④ durable 无卡死任务 — 通过
- `SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=513 / failed=226 / cancelled=15，非终态=0（较第1轮 497/221/14 正常累积）。无卡死，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：API 实测 roles[ocr] = `ocr_local_omlx/GLM-OCR-bf16`、ready=true、capability_status=specialized_whitelisted、role_revision=65；备份 `.pre-ocr-rebind-20261008` 在位。bindings.json 当日 04:30 有更新（revision 63→65，实现师侧所为），ocr 目标绑定未变。后端 01:45 重启已使绑定生效，本轮无需再改绑/重启，以真实调用取证。
- 实测（全经产品 API，oMLX pid 2264，隔夜冷态 RSS 464,672KB 起步）：
  1. OCR 视觉探针 #1（`POST /api/ai-gateway/roles/ocr/probe-visual`）→ HTTP 200，passed=true，9,877ms（冷加载GLM-OCR-bf16），RSS→33,926,336KB；
  2. 翻译探针（`POST /api/ai-gateway/probe`，dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed，322ms（翻译模型自昨夜仍驻留，热响应）；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **138ms**，RSS 33,926,608KB —— 共存无互斥（co_resident=true），与历轮一致。
- 共存结论已追记 `../ocr_rebind_20260929/mem_probe.md` 新纪元第2轮节。
- 证据：`ocr_probe_r2_1.json`、`translation_probe_r2.json`、`ocr_probe_r2_2.json`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **151**（第1轮收盘148后 +3，新纪元第1轮测试正常累积，按红线保留）。
- ego-browser 空间178（用后即关）：5186 首页「请选择项目（共151个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 关闭、`/api/projects` 复验 **151=151 零新建**。
- 如实记录：首页存在两个新建入口按钮（「新建项目」与「新建中国临床试验方案写作项目」），本次冒烟走「新建项目」入口（与前轮同路径）；文本定位器对两按钮歧义，改用快照ref定位成功——非缺陷，仅测试操作记录。

## 红线自检
未碰 live 8910/8911/医学监查并行进程；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；未清库未删历史未 reset（151基线含历史测试项目如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（147/157）保留。

## 遗留上报（不阻断）
- git 未提交漂移（集成人职权）：`services/api/app/ai_task_runner.py`、`services/api/app/medical_writing_synopsis_import.py` 及 tests 侧数文件仍为 M 状态（与第1轮上报一致，未收编）。
- vite/后端 01:45–01:46 的重启为实现师侧动作（新指纹 api-70177dabe5ffaf25 两侧一致），本管理员未参与、未干预。
