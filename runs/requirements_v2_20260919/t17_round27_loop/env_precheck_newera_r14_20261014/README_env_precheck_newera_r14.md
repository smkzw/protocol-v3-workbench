# 环境预检与清洁 · 新纪元第14轮证据（本ask第2轮）（2026-10-14 22:41–22:52 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过（r13 后实现师侧双服务已换新进程，本轮零重启）
- 前端 5186：HTTP 200；vite **pid 81087（r13 的 81593 已被换新）**，进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪。
- 后端 5301：**pid 7724（2026-10-14 22:39:41 启动，r13 的 96580 已被换新）**；`/api/health`=ok（runtime_store ok、共享语料 ok）。
- 构建指纹：`/api/runtime-readiness` 自报 `api-a744e7bfaf0cdeae` = vite `/runtime-build.json` 期望同值 = 经 5186 代理读同值 **MATCH**（ready=true、missing=[]、independent_ai ready=mtplx）→ 无漂移，无需重启。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检时 arbiter=null（后端 22:39 刚重启、首次 AI 活动前未初始化——历轮 r2 判例同型，端点自报 ok 非异常）、omlx healthy 非驻留、mtplx process_not_running（最小驻留正常卸载）；探针后 arbiter=omlx resident、users 0、queue 空（全程无 refused）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 8 个，全部为并行线/他线资产，本子系统遗留空间 **0**：42「0.2.0 审定备选与检验衔接验收」（入排线，r12 起历轮保留；ownership 本轮显示为 agent，前两轮为 agentDelegatedToUser——归属线不变，非本子系统资产，继续保留）；54/60/67/73/80/83/87（R38C–R44C medical monitoring/PV/QA/PSO——**医学监查并行线空间，红线不碰，全保留**）。
- headless 进程 0；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 **0 命中**（无需清理）。

## ④ durable 无卡死任务 — 通过
- isolated_runtime `medical_writing_durable_jobs.sqlite3`（只读）：completed=619 / failed=266 / cancelled=23，**非终态=0**（较 r13 604/254/23 累积 +15/+12/+0，正常）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` bindings.ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted、enabled）；API 实测（新 5301 进程加载后）roles[ocr] availability=available、ready=true、current_runnable=true。备份 `.pre-ocr-rebind-20260928`/`.pre-ocr-rebind-20261008` 在位。PADDLE key 不存在（历轮穷尽排查+主会话裁决，本地路线）——无需改绑/重启，以真实调用取证。
- 实测（全部经产品 API；**oMLX 新进程 pid 99765**；590s 客户端超时）：
  1. OCR 视觉探针 #1 → **passed**（HTTP 200，14,421ms，冷加载）；RSS 63,328→16,381,504KB；
  2. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 298ms；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **125ms**，RSS 16,383,648KB 稳定 —— 双模型同驻共存无互斥（co_resident=true）。新 oMLX 进程 RSS 基线较 r13（33.9GB）约减半，进程内存记账不同，加载/切相/共存行为不变。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-13 第14轮节标题、22:44 实测）。
- 证据：`ocr_probe_r14_1.json`、`translation_probe_r14.json`、`ocr_probe_r14_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建；截图未取得，如实记录）
- 基线 `GET /api/projects`（经 5186 代理）→ **185**（r13 收官 181 后自然 +4，作为本轮基线如实记录）。
- ego-browser 空间（多个用后即关，最终列表复核仅剩 8 个并行线空间）：5186 项目总看板渲染完整，「请选择项目（共185个）」UI=API 一致 → 打开「新建项目」→ 对话框「新建研究方案项目」打开：两建项模式在（从零开始/导入方案摘要及其说明）、试验药物/适应症/研究分期/取消/创建并进入全在 → 点「取消」→ DIALOG_CLOSED=true、看板复现「共185个」→ `/api/projects` 复验 **185=185 零新建**（整个冒烟含重试共 4 轮开/关对话框，计数始终 185）。
- 如实记录：本轮截图未取得——ego 浏览器窗口当前视口 0×0（`window.innerWidth=0`），`page.screenshot` 报 "Cannot take screenshot with 0 width"，CDP `Page.captureScreenshot` 超时；属 ego 窗口状态问题，非产品缺陷（页面渲染/交互/API 全部正常，对话框开关有文本与布尔证据）。对话框要素核验以 innerText 为准：字面「建项方式」一词不在 innerText 中（r13 快照树中有），两模式标签实际在，功能等价。

## 红线自检
未碰 live 8910/8911/医学监查并行进程与并行线 ego 空间（54/60/67/73/80/83/87）；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002）；本轮零服务重启零进程杀停；未清库未删历史未 reset（185 基线如实保留；durable 库只读查询）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录。

## 遗留上报（不阻断）
- ego 浏览器窗口 0×0 视口导致截图能力暂不可用（影响的是证据留档手段，不影响被测系统）；如后续轮次需要截图证据，需先恢复 ego 窗口可见尺寸。
