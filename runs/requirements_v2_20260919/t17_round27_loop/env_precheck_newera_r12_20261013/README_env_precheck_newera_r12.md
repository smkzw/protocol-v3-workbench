# 环境预检与清洁 · 新纪元第12轮证据（2026-10-13 02:54–03:00 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过（含一次后端重启修复指纹漂移）
- 前端 5186：HTTP 200；vite pid 81593（延续第11轮进程），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪。
- 后端 5301：**预检发现指纹漂移**——运行中 pid 81592（01:46 起）自报 `api-cf7735154a90b641` ≠ vite `/runtime-build.json` 期望 `api-2d4246c7ddcf6513`（HEAD=ffa09237，实现师在后端启动后又有源码更新）。按产品自身指引（`frontend/src/runtimeReadiness.js` 漂移即重启后端）与历轮判例（新纪元 r1）：重启前核验 durable 非终态=0、编排器 users 0/0 队列空（无任务可被打断）→ `kill -TERM 81592`（1s 端口释放）→ 历轮同款脚本 `zsh runs/requirements_v2_20260919/t17_round27_loop/start_5301_round27.sh` → 新 pid 96580。启动预检 5 云端 key 未导出警告为历轮基线（本地模型路由不依赖）。
- 重启后：`/api/health`=ok；`/api/runtime-readiness` 自报 `api-2d4246c7ddcf6513` = vite 期望 **MATCH**（ready=true），经 5186 代理读同值 ✓。vite 无需重启（env 正确，dev 期望指纹按源码树现算）。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检时 arbiter=mtplx 驻留（users 0/0、队列空）；探针后 arbiter=omlx、queue 空、mtplx 按最小驻留正常卸载（全程无 refused）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 1 个：42「0.2.0 审定备选与检验衔接验收」（ownership=agentDelegatedToUser，入排线，已移交用户态）——**本子系统遗留空间 0**，保留未动。
- headless 进程 0（camoufox MCP 本轮已不在运行）；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- isolated_runtime 库：completed=603 / failed=253 / cancelled=23，**非终态=0**（重启前与重启后两次核实；较第11轮 602/252/23 各增，正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，enabled）；role_revision=118（实现师侧有绑定文件更新，ocr 绑定目标未变），重启后 API 实测 roles[ocr] availability=available、ready=true（生效确认）；备份 `.pre-ocr-rebind-20261008` 与 `.pre-ocr-rebind-20260928` 在位。PADDLE key 不存在（历轮穷尽排查+主会话裁决，走本地路线）——绑定目标状态已达成，本轮改绑/重启动作仅为①中指纹漂移修复所需，OCR 以真实调用取证。
- 实测（全部经产品 API；oMLX pid 25352；590s 客户端超时）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200），9,426ms = 页缓存热加载（切相窗口浮动特性再次确认：历轮 169s–478s，本轮极短）；RSS 98,016→33,889,792KB；
  2. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 267ms；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **93ms**，RSS 33,892,240KB 稳定 —— 双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-13 第12轮节）。
- 证据：`ocr_probe_r12_1.json`、`translation_probe_r12.json`、`ocr_probe_r12_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理，重启后复验）→ **180**。
- ego-browser 空间 51（用后即关）：5186 项目总看板「请选择项目（共180个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 对话框关闭、`/api/projects` 复验 **180=180 零新建**。冒烟空间已关（复验列表仅剩用户态 42）。

## 红线自检
未碰 live 8910/8911/医学监查并行进程（重启仅限本子系统 5301，历轮判例路径）；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；未清库未删历史未 reset（180 基线如实保留；durable 库未动）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（42，用户态）保留。

## 遗留上报（不阻断）
- 无新增。指纹漂移已本轮修复；实现师侧绑定文件更新（revision 114→118）不改变 ocr 绑定目标，无碍。
