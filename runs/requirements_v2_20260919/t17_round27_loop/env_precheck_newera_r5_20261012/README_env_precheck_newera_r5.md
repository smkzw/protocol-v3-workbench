# 环境预检与清洁 · 新纪元第5轮证据（2026-10-12 01:36–01:50 CST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 71300（`lsof -iTCP:5186 -sTCP:LISTEN` 确认），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓ 无脚枪。
- 后端 5301：pid 71299（与 vite 成对重启，本轮未动）`/api/health`=ok；`/api/runtime-readiness` 自报 `backend_build_id=api-ef5970b7761b7b28` = vite `/runtime-build.json` 期望 **MATCH**（ready=true），经 5186 代理读同值 ✓。HEAD=e6dec9bd。
- 编排器 `/api/model-lifecycle/status`：status=ok；预检时 arbiter=mtplx 驻留（并行线 01:34:03 刚完成 triage@mtplx 切相）；探针后 arbiter=omlx、queue 清空、mtplx 按最小驻留正常卸载。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 5 个：2、11（CI 线）、20「R35B 医学监查子系统验收测试」、21「r35-c-tester」（医学监查线）、23「入排审核 0.2.0 构建验收」（入排线）——**本子系统遗留空间 0**，五个并行线空间全部保留未动。
- headless 进程 0（camoufox MCP 本轮已不在运行）；`/tmp/ego_*.mjs` 残留 0。

## ③ 上轮测试缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp find 扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- isolated_runtime 库：completed=570 / failed=241 / cancelled=21，**非终态=0**（较第4轮 568/239/21 各增，正常累积）。无卡死无悬置，运维帽无适用对象。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true）
- 绑定在库：`ai_role_bindings.json` ocr = `ocr_local_omlx/GLM-OCR-bf16`（specialized_whitelisted，enabled）；role_revision=85（重启已加载生效）；备份 `.pre-ocr-rebind-20261008` 与 `.pre-ocr-rebind-20260928` 在位。PADDLE key 不存在（历轮穷尽排查+主会话裁决，走本地路线）——绑定目标状态已达成，无新增改绑/重启，以真实调用取证。
- 实测（全部经产品 API；探测开始时仲裁器=mtplx 驻留；oMLX pid 25352）：
  1. OCR 视觉探针 #1 首发入队（translation@omlx position 1）——编排器切相窗口等待（并行线 01:24-01:34 双向切相后窗口重置），curl 300s 客户端超时断开（请求本体留队，动作日志 `t17_round21_model_scheduler/actions.log` 01:36:31 queue_enter 可查）；
  2. 重发探针 #1（590s 超时）→ **passed**（HTTP 200），19,815ms——切相窗口结束获批+GLM-OCR-bf16 加载一气呵成；
  3. 翻译探针（dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX，structured {"status":"ok"}）→ passed 282ms；RSS 33,882,640→33,884,352KB；
  4. OCR 视觉探针 #2（翻译后热复测）→ passed **109ms**，RSS 33,884,720KB 稳定 —— 双模型同驻共存无互斥（co_resident=true），与历轮一致。
- 多线共享观察（记入 mem_probe 供测试排程参考）：本轮 OCR 实际排队窗口 ~7.3 分钟（与日志中 478s/573s 历史窗口一致），属编排器队列+最小驻留设计行为，非卡死非阻断；产品内调用不设人为 300s 超时，对正式运作人工负担无影响。
- 结论已追记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-12 第5轮节）。
- 证据：`ocr_probe_r5_1.json`（重发成功响应）、`translation_probe_r5.json`、`ocr_probe_r5_2.json`、`omlx_pid.txt`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_translation.txt`、`omlx_rss_after_ocr2.txt`、`timeline.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **165**。
- ego-browser 空间 26（用后即关）：5186 项目总看板「请选择项目（共165个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 对话框关闭、`/api/projects` 复验 **165=165 零新建**。冒烟空间已关（复验列表仅剩并行线 2/11/20/21/23）。

## 红线自检
未碰 live 8910/8911/医学监查并行进程；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002；切相排队与 mtplx 卸载均为编排器自动行为）；未清库未删历史未 reset（165 基线如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录；并行线 ego 空间（2/11/20/21/23）保留。

## 遗留上报（不阻断）
- 无新增。多线高峰时段 OCR 冷启动排队窗口（分钟级）已在 mem_probe 记录，供执行秘书排程参考，不构成缺陷。
