# 环境预检与清洁 · 第3轮证据（2026-10-05 08:08–08:15 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 77716（10-05 06:13:21 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`（`--host 127.0.0.1 --port 5186 --strictPort`）；经代理读 `/api/health`=ok。
- 后端 5301：pid 18213（10-04 21:42:22 起），`/api/health`→ok。
- 构建指纹：5186 `/runtime-build.json` 期望 `api-9e5511fbd42397bf` == 后端 `/api/runtime-readiness` 自报 `api-9e5511fbd42397bf`（ready=true、missing=[]）。
- 【如实记录·非门禁失败】HEAD=eb0f1b6（10-04 15:23，≥f72fa95）之下有 9 个未提交改动路径（`git status --porcelain -- services/api frontend/src`：App.jsx、errorContract、runtimeReadiness、model_lifecycle_orchestrator.py、writing_reference_repository.py、writing_reference_translation_batch.py 等）——实现师第2/3轮修订批以工作树形态交付，前后端指纹互相一致故版本门不拦；属交付卫生事项（待实现师提交），非本轮预检失败项。
- 编排器：`/api/model-lifecycle/status`→status=ok；omlx 与 mtplx 均 healthy+resident、队列空。8002 仍被用户侧遗留 pid 1759 占用（MTPLX.app 本体已退出、守护服务器存活，按主会话裁定继续不碰）——但切相已不再被拒（见⑤）。

## ② 测试者环境隔离 — 通过
- ego-browser 清点：2 个 agent 遗留空间（id 39"入排1001资料更正贯通"、id 41"SMOKE-r2-3 chain round2 attempt3"，均上轮/并行线收尾后残留）→ 已逐一 `finish({keep:[]})` 关闭，复核 0。
- 用户自有空间：0。headless/测试浏览器残留进程：0。

## ③ 上轮缓存清理 — 通过（零删除）
- `find t17_round27_loop`（.DS_Store/*.tmp/__pycache__/*.swp/*~）→ 0 命中。守不清历史红线。

## ④ durable 无卡死任务 — 通过
- `durable_mw_jobs`（运行中 5301 实际 WORKBENCH_RUNTIME_DIR）：completed=329 / failed=164 / cancelled=3 / **非终态=0**（较第2轮 287/150/1 为round-2测试正常增量）。

## ⑤ OCR 环境侧清偿 — 通过（第2轮阻断已解除，序列恢复）
- 缺口重读：retest_r26.md:68（"OCR API Key is not configured for the Paddle provider（0/4）"，grep 命中1）。
- 密钥复核：`grep -c PADDLE ~/.config/cms-medical-workbench/ai-runtime.env`→0；运行中 5301（pid 18213）进程环境 0 命中——维持主会话裁决路线。
- 绑定核验：revision 26，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted，capability_verified_at=2026-10-05T06:09:44Z，随本轮探针#1更新）；备份 `.pre-ocr-rebind-20260928` 仍在。
- **阻断解除说明**：第2轮的8002阻断（DIAG/env_blocker_8002_20261004.md）本轮只读探测发现 1759 仍在、未做任何处置；实际解除来自实现师对 `model_lifecycle_orchestrator.py` 的修订（上列未提交批次）：切相不再要求先停不拥有的服务器（actions.log 08:05:41 `phase_switch translation@omlx` granted，近期无 `refused/server_unowned`），双服务器并存由 identity/exclusion/memory 前置校核把关。防双载红线未被绕过杀进程——与本岗裁定禁区无冲突。
- 实测序列（经产品 API、真实读图推理）：
  1. OCR 视觉探针 #1：HTTP 200，`visual_probe={passed:true, ocr_local_omlx/GLM-OCR-bf16/omlx, 1797ms}` → `ocr_probe_visual_r3probe1.json`
  2. 翻译探针（dawncr0w）：HTTP 200，passed=true，structured={"status":"ok"}，255ms → `translation_probe_r3.json`
  3. OCR 视觉探针 #2（翻译后热复测）：passed=true，118ms → `ocr_probe_visual_r3probe2.json`
- 共存：8001 模型列表 GLM-OCR-bf16 与 dawncr0w 并存，RSS ~9.0 GB 稳定；已记入 `../ocr_rebind_20260929/mem_probe.md`（2026-10-05 节，含阻断解除前情）。
- 【如实记录·非本轮新问题】actions.log 08:05:41 一个 translation@omlx 派发排队 600.05s 才获相——与已立案 P2（跨相队头等待）同型。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→109（round-2 测试较上轮 100 新增 9，正常）。
- ego-browser（space 52，用后即关）：打开 5186 →"请选择项目（共109个）"（UI=API）→ 点"新建项目"→ 对话框"新建医学写作项目"打开（建项方式/试验药物/适应症/研究分期四要素俱全）→ 点"取消"不提交 → 关闭后快照对话框 0 命中、UI/API 均 109、零新建。
- 证据：`smoke_r3_home_snapshot.txt`、`smoke_r3_dialog_open_snapshot.txt`、`smoke_r3_dialog_closed_snapshot.txt`。

## 红线自检
未碰 live 8910/医学监查/共享runtime；模型服务器只经编排器（全部探针走产品 API；8002 的 pid 1759 全程未触碰）；未清库未删历史；未改产品代码；仅关闭 agent 遗留空间。
