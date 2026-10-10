# 环境预检与清洁 · 新纪元第3轮证据（2026-10-09 19:53–20:05 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite 进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301` ✓（pgrep+ps eww）。
- 后端 5301：`/api/health`=ok；`/api/runtime-readiness` 自报 `api-291fee25254cca4f` = vite `/runtime-build.json` 期望 **MATCH**，ready=true（当日新进程对，指纹一致）。
- 编排器 `/api/model-lifecycle/status`：status=ok；初始 arbiter=mtplx（MTPLX owned驻留、inflight=0 最小驻留空闲）；omlx healthy=true。
- git HEAD=2ca9ba8c（10-09 checkpoint：新纪元R2预聚合无损暂停）≥ 9339a0c2 ✓。

## ② 测试者环境隔离 — 通过
- ego-browser 空间 5 个逐一甄别：147（入排线）、157（R26B医学监查线）、184（CI1007竞品情报线，tab=药监局CDE官网+competitive-intelligence-workflow file://页面）、186（R30B医学监查线，tab=localhost:5178/monitoring）、188（R30-C，ownership=user）——均非本子系统测试者遗留，全部保留未动。
- headless 匹配进程 0；`/tmp/ego_*.mjs` 残留 0；冒烟空间用后即关。

## ③ 上轮缓存清理 — 通过
- `t17_round27_loop/` 下 .DS_Store/*.tmp/*~/*.swp 扫描 0 命中（find 实跑）。新增 r2-A/r2-B/r2-C、retest_r2_newera_* 为第2轮测试证据，保留。

## ④ durable 无卡死任务 — 通过
- `SELECT status,COUNT(*) FROM durable_mw_jobs GROUP BY status` → completed=526 / failed=229 / cancelled=17，非终态=0（较第2轮 513/226/15 正常累积）。无卡死。

## ⑤ OCR 环境侧清偿 — 通过（ocrFixed=true，含一次切相迟滞的如实记录）
- 绑定在库：roles[ocr] = `ocr_local_omlx/GLM-OCR-bf16`、ready=true、specialized_whitelisted、availability=available、role_revision=68；备份 `.pre-ocr-rebind-20260928`/`.pre-ocr-rebind-20261008` 在位。无需再改绑，以真实调用取证。
- **异常如实记录**：19:54 OCR 探针 #1 客户端 300s 超时（HTTP=000）。诊断：仲裁器 mtplx→omlx 切相排队约 6 分钟未放行（期间 users 0/0、mtplx inflight=0、队列悬挂 {phase:translation, server:omlx}）；oMLX 8001 直连健康（/v1/models 正常、RSS 472,576KB 冷态）。19:58 复查队列已自行放行（arbiter=omlx、omlx resident=true），未动用运维帽强制释放。切相迟滞现象与历轮秒级不同，已如实追记 mem_probe 供实现师侧留意（与今日 HEAD 2ca9ba8c 变更是否同源未下结论）。
- 实测（全部经产品 API，oMLX pid 2264）：
  1. OCR 视觉探针 #1（切相后重试）→ HTTP 200 passed **145ms**，RSS→33,917,776KB；
  2. 翻译探针（dawncr0w，structured {"status":"ok"}）→ passed **314ms**；
  3. OCR 视觉探针 #2（翻译后热复测）→ passed **109ms**，RSS 33,919,472KB —— 共存无互斥（co_resident=true），与历轮一致。
- 共存结论与切相迟滞记录已追记 `../ocr_rebind_20260929/mem_probe.md` 新纪元第3轮节。
- 证据：`ocr_probe_r3_1.json`、`translation_probe_r3.json`、`ocr_probe_r3_2.json`、`omlx_rss_before.txt`、`omlx_rss_after_ocr1.txt`、`omlx_rss_after_ocr2.txt`。

## ⑥ 新场景冒烟 — 通过（零新建）
- 基线 `GET /api/projects`（经 5186 代理）→ **154**（第2轮收盘151后 +3，第2轮测试正常累积，按红线保留）。
- ego-browser 冒烟空间（用后即关）：5186 首页「请选择项目（共154个）」（UI=API 一致）→ 点「新建项目」→ 对话框「新建研究方案项目」打开，要素齐全（建项方式两模式/试验药物/适应症/研究分期/取消/创建并进入写作）→ 点「取消」→ 关闭、`/api/projects` 复验 **154=154 零新建**。

## 红线自检
未碰 live 8910/8911/医学监查/竞品情报并行线进程与 ego 空间；模型服务器只经编排器（全部模型流量经产品 API 探针触发，本轮未动用 release/admin unload，切相自行完成）；未清库未删历史未 reset（154基线如实保留）；未动 immutable；未改产品代码；共享文件仅追加 mem_probe.md 与新建本证据目录。

## 遗留上报（不阻断）
- **编排器切相迟滞**：mtplx→omlx 切相本次耗时约 6 分钟（历轮秒级），期间探针客户端 300s 超时一次。属观察项非立案缺陷（队列最终自行放行、无卡死残留），如复现建议实现师侧核查今日 HEAD 变更后仲裁器行为。
- git 未提交漂移（集成人职权）：服务代码与 tests 侧 M 状态文件历轮上报未收编，本轮未再逐项清点。
