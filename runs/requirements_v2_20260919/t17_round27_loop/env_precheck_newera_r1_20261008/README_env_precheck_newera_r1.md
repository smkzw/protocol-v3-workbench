# 环境预检与清洁 · 新纪元第1轮证据（2026-10-08 08:00–08:10 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过（含一次后端重启修复指纹漂移）
- 前端 5186：HTTP 200；vite pid 9202（10-07 18:18 起，未动），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓（无脚枪）；经代理 `/api/health`=ok。
- 后端 5301：重启前 pid 6663（10-07 18:14:07 起）`/api/health`=ok，但**构建指纹漂移**：运行中后端自报 `api-a0d262b6350b9b5c` ≠ 当前源码树期望 `api-b88acb53b5aff176`（vite dev 中间件 `/runtime-build.json` 逐请求现算）。根因定位：`services/api/app/medical_writing_repository.py`（10-08 00:52 改）与 `services/api/app/protocol_workflow/legacy/mutation_route_inventory.py`（00:55 改）在后端启动后才更新，且 HEAD `9339a0c2` 于 10-08 07:42:17 提交（晚于后端启动）→ 后端侧旧。产品自身漂移指引即"重启后端5301"（`frontend/src/runtimeReadiness.js:27`）；vite 无需重启（env 已正确、dev 期望指纹本就按源码树现算，重启vite不改变比对基准）。
- 重启：`kill -TERM 6663`（3s 内退出、端口释放）→ `zsh t17_round27_loop/start_5301_round27.sh` → 新 pid 43270。预检如实警告 5 个云端 key 未导出（DEEPSEEK/PADDLE_OCR/OPENCODE/CMS_ROUTER/MTPLX，与 R26 起历轮基线一致；本地模型路由不依赖）。
- 重启后：`/api/runtime-readiness` 自报 `api-b88acb53b5aff176` = vite 期望值 **MATCH**，ready=true、missing=[]；经 5186 代理读同值 ✓。
- 编排器：`/api/model-lifecycle/status` status=ok。探测前：mtplx 驻留（owned pid 68389）、omlx 健康 idle、队列空；探测切相后：omlx 驻留（arbiter=omlx，users 0，queue 空）、mtplx 被编排器按最小驻留正常卸载（`owned:false, reason:process_not_running, release_unconfirmed:false`）——设计内轮换，非故障。

## ② 测试者环境隔离 — 通过
- ego-browser 空间清单（`listTaskSpaces()`）：id 147「入排1006V1正式入口验证」、id 157「R26B 医学监查验收」均属并行线 → 保留；本子系统测试者遗留空间 0；冒烟空间 160 用后已关（`finish({keep:[]})` → closedSpace=true，复验清单仅剩 147/157）。
- headless 测试进程残留 0；pid 2405/2371 playwright-mcp 为 harness 常驻 MCP 基础设施（周五起、空闲），非测试残留，未动。

## ③ 上轮缓存清理 — 通过
- `t17_round27_loop/` 内 .DS_Store/*.tmp/*~/*.swp 扫描 0 命中。
- `/tmp` 清出上轮（10-03）测试会话脚本残留 23 个 `ego_*.mjs`（先 lsof 核实无进程占用，再删，余 0）。
- r26 提过的临时上传端口 5397/5398 已空闲；全机监听端口清点无本线异常残留。

## ④ durable 无卡死任务 — 通过
- `medical_writing_durable_jobs.sqlite3`：`SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=491 / failed=221 / cancelled=14 / **非终态=0**（较 r12 的 484/220/13 各增，历轮测试正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（改绑已在库，本轮重启生效并实测取证）
- 缺口重读：`t17_round26_loop/retest_r26.md`（行68/75：NCT01393405 Prot_000.pdf 解析 `OCR API Key is not configured for the Paddle provider（0/4）`，PADDLE 云端 key 属集成人职权、测试者不伪造）。
- key 来源复核：`~/.config/cms-medical-workbench/` 仅有 `ai-runtime.env`，其中 PADDLE 命中 0；isolated_runtime 各文件仅 `api_key_env` 字段名引用无值；运行中进程环境亦无 —— 与主会话裁决一致（本机不存在），走 `ocr_local_omlx`（GLM-OCR-bf16@8001，本地免key）路线。
- 改绑状态：`ai_role_bindings.json` 中 ocr 角色已绑 `ocr_local_omlx/GLM-OCR-bf16`（上轮会话已落，capability_status=specialized_whitelisted）；重启前后经 `/api/ai-gateway/roles/status` 双验 role_revision 59（探针后 60）。本轮未改产品代码；按 ask 建新鲜备份 `ai_role_bindings.json.pre-ocr-rebind-20261008`（旧备份 `.pre-ocr-rebind-20260928` 仍在）。
- 实测（全经产品 API，oMLX pid 2264，详细表见 `../ocr_rebind_20260929/mem_probe.md` 新纪元第1轮节）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200=严格读码 CMS VISION 7429 并落库）9,987ms，RSS 66,752→33,914,912KB（GLM-OCR-bf16 驻入）；
  2. 翻译探针（dawncr0w Hy-MT2-30B，structured `{"status":"ok"}`）→ **passed** 321ms，RSS 33,916,336KB（翻译模型载入同进程）；
  3. OCR 视觉探针 #2（翻译后热复测）→ **passed** **143ms**，RSS 33,916,496KB —— 翻译加载后 OCR 仍毫秒级热响应=**双模型同驻共存无互斥**（co_resident=true），结论与历轮一致。
- 如实说明：探针 #1 调用命令误写致同窗连发两次（首次 9,987ms 做功、第二次热态复用），证据文件存首次响应；多出一次为只读探针无副作用。
- 证据：`ocr_probe_visual_newera1_1.json`、`translation_probe_newera1.json`、`ocr_probe_visual_newera1_2.json`、`omlx_rss_*.txt`、`role_status_post_restart.txt`。
- ocrFixed=true：L3 缺陷（OCR key 缺失致语料解析冻结）的环境侧清偿经真实 OCR 调用验证在本轮可用。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`（经 5186 代理）→ **147**（r12 为 145，环内测试 +2 正常）。
- ego-browser（用后即关）：5186 打开首页「请选择项目（共147个）」（UI=API）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ **取消不提交** → 对话框关闭、UI 仍 147、API 复验 147 = **零新建**。冒烟空间已关。
- 证据：`smoke_newera1_home.txt`、`smoke_newera1_dialog_open.txt`、`smoke_newera1_dialog_closed.txt`。

## 红线自检
未碰 live 8910/8911/8900/医学监查（5178 前端与 8911 后端进程未动）；模型服务器只经编排器（本轮全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；未清库未删历史未 reset；未动 immutable；未改产品代码（OCR 为纯环境侧绑定+重启）；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间保留。

## 遗留上报（不阻断，转实现师/集成人）
- 后端未提交漂移仍在：`services/api/app/ai_task_runner.py`、`services/api/app/medical_writing_synopsis_import.py`（git status M，自 10-04/10-05 遗留未收编）——不影响本轮指纹一致性判定（两侧均按当前盘上源码树计算），但需集成人收编。
- 启动预检 5 云端 key 警告为历轮基线（本地路由不依赖）；若后续轮次需云路 fallback，仍属集成人职权。
