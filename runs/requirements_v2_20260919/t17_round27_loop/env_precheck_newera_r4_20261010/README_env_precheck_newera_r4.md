# 环境预检与清洁 · 新纪元第4轮证据（2026-10-10 02:44–02:56 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite 进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓（pgrep+ps eww）。
- 后端 5301：`/api/health`=ok；`/api/runtime-readiness` 自报 `api-b7be2365d992b0aa` = vite `/runtime-build.json` 期望 **MATCH**，ready=true（当日又换新进程对，指纹一致）。
- 编排器 `/api/model-lifecycle/status`：status=ok；初始 arbiter=mtplx（owned驻留、users 0/0、queue空）；omlx healthy=true 未驻留。
- git HEAD=2ca9ba8c ≥ 9339a0c2 ✓（与第3轮同HEAD，服务代码工作树有变化致指纹更新）。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 4 个：147（入排线）、157（R26B医学监查线）、184（CI1007竞品情报线，tab=CDE+竞品全景）、188（R30-C，ownership=user）——均非本子系统测试者遗留，保留；第3轮的186已被并行线自行关闭。
- headless 匹配进程 0；`/tmp/ego_*.mjs` 残留 0；冒烟空间用后即关（复验确认，见⑥）。

## ③ 上轮缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp 扫描 0 命中（find 实跑）。新增 r3-A/r3-B/r3-C、retest_r3_newera_* 为第3轮测试证据，保留。

## ④ durable 无卡死任务 — 通过
- `SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=536 / failed=232 / cancelled=20，非终态=0（较第3轮 526/229/17 正常累积）。无卡死。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true；切相迟滞复现确证）
- 绑定在库：roles[ocr] = `ocr_local_omlx/GLM-OCR-bf16`、ready=true、specialized_whitelisted、availability=available、role_revision=72；备份 `.pre-ocr-rebind-20260928`/`.pre-ocr-rebind-20261008` 在位。无需再改绑，以真实调用取证。
- **切相迟滞复现（第3轮观察项本轮确证为可复现）**：OCR 探针 #1 服务端耗时 354,587ms（≈5.9分钟，本轮客户端590s窗口内完成、未超时）——初始 arbiter=mtplx、omlx 未驻留，探针触发 mtplx→omlx 切相等待约5.9分钟后完成。对比第1/2轮秒级~10s、第3轮~6分钟自行放行，该现象两轮连续出现。oMLX 8001 直连全程健康；未动用运维帽（探针最终完成、无卡死残留）。已追记 mem_probe，持续上报供实现师侧核查。
- 实测（全部经产品 API，oMLX pid 2264）：
  1. OCR 视觉探针 #1 → HTTP 200 passed（RSS 462,224→33,921,920KB，含切相等待354.6s）；
  2. 翻译探针（dawncr0w，structured {"status":"ok"}）→ passed **263ms**；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **124ms**，RSS 33,923,872KB —— 共存无互斥（co_resident=true），与历轮一致。
- 共存结论与切相迟滞复现记录已追记 `../ocr_rebind_20260929/mem_probe.md` 新纪元第4轮节。
- 证据：`ocr_probe_r4_1.json`、`translation_probe_r4.json`、`ocr_probe_r4_2.json`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_ocr2.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **157**（第3轮收盘154后 +3，第3轮测试正常累积，按红线保留）。
- ego-browser 冒烟空间（用后即关）：5186 首页「请选择项目（共157个）」（UI=API 一致）→ 点「新建项目」（ref=12，与历轮同入口）→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 关闭、`/api/projects` 复验 **157=157 零新建**。
- 空间关闭复验：finish 后首次列表曾读到未落定状态（仍含195），3秒后复验确认空间195已关闭，剩余147/157/184/188全部为并行线/用户空间。

## 红线自检
未碰 live 8910/8911/医学监查/竞品情报并行线进程与 ego 空间；模型服务器只经编排器（全部模型流量经产品 API 探针触发，未手工启停 8001/8002，未动用 release/admin unload）；未清库未删历史未 reset（157基线如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录。

## 遗留上报（不阻断）
- **编排器切相迟滞（第3轮上报，本轮复现确证）**：mtplx→omlx 切相连续两轮耗时约6分钟（历轮秒级）。探针均最终完成、无卡死残留，暂为观察项；建议实现师侧核查（第3轮起才出现，此前历轮同场景秒级）。
- git 未提交漂移（集成人职权）：历轮上报的 M 状态文件未收编，本轮未再逐项清点。
