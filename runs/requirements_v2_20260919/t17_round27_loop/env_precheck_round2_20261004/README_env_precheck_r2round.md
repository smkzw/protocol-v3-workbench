# 环境预检与清洁 · 第2轮证据（2026-10-04 15:38–15:55 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 61928（10:10:13 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`、启动参数 `--host 127.0.0.1 --port 5186 --strictPort`；经代理读 `/api/health`=ok。
- 后端 5301：pid 61235（10:03:18 起），`/api/health`→ok。
- 构建指纹：5186 `/runtime-build.json` 期望 `api-0bee035a068f0e5a` == 后端 `/api/runtime-readiness` 自报 `api-0bee035a068f0e5a`（ready=true、missing=[]）。随1004批次（门重设计/前端深对齐）更新且两侧一致；10:41 提交 c41ad12 的源码在 10:03 后端启动前已落盘（git status 对 services/api、frontend/src 无未提交漂移），无需重启。HEAD=eb0f1b6（2026-10-04 15:23，≥f72fa95）。
- 编排器：`/api/model-lifecycle/status`→status=ok（omlx healthy 非驻留；mtplx healthy+resident——但其监听者非本部署所属，见⑤的阻断分析）。

## ② 测试者环境隔离 — 通过（零处置）
- ego-browser 清点：0 个空间（第1轮遗留与昨日并行空间均已由各自属主收尾）。
- headless/测试浏览器残留进程：0。

## ③ 上轮缓存清理 — 通过（零删除）
- `find t17_round27_loop`（.DS_Store/*.tmp/*.pyc/__pycache__/*~/*.swp）→ 0 命中；第1轮后新增文件全为证据/日志/规格档（r1-A..D、retest_r1*、HANDOFF_1004_PAUSE、OWNER_DECISIONs、fe_cleanup_r1、model_bench 等），守不清历史红线零删除。

## ④ durable 无卡死任务 — 通过
- `durable_mw_jobs`：completed=287 / failed=150 / cancelled=1 / **非终态=0**（较第1轮 263/144/1 为本轮测试正常增量）。

## ⑤ OCR 环境侧清偿 — 绑定侧全部就绪；**实测被8002外来占用阻断（升级主会话）**
- 缺口重读：retest_r26.md:68（"OCR API Key is not configured for the Paddle provider（0/4）"）。
- 密钥复核：`grep -c PADDLE ~/.config/cms-medical-workbench/ai-runtime.env`→0；运行中 5301（pid 61235）进程环境 0 命中——key 仍不存在，维持主会话裁决路线。
- 绑定核验：`ai_role_bindings.json` revision 23，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted，capability_verified_at=2026-10-03T16:16Z 即第1轮实测时间）；备份 `.pre-ocr-rebind-20260928` 仍在；绑定随当前后端启动已生效。
- **实测受阻断**：`POST /api/ai-gateway/roles/ocr/probe-visual` → HTTP 502 `CompositePipelineUnavailableError`（0.16s，证据 `ocr_probe_visual_r2probe1.json`）。
- 根因链（全部本ask实查）：
  1. 8002 现有监听者 pid 1759（`Python -P -m mtplx.server.openai --model …Flash-Next-MTPLX-Optimized-Speed --port 8002`，04:44:19 起，父进程 launchd，cwd /private/tmp）；
  2. `/Applications/MTPLX.app`（pid 1203）04:43:21 启动——早于 1759 整 58 秒，判断 1759 系**用户自有 MTPLX 桌面应用**拉起的服务器；
  3. 编排器身份核验 owned=false（台账 pid 91607 已于 03:44:00 被编排器自己 SIGTERM），对 1759 拒绝行使停止——`refused/server_unowned: refusing to stop a server we do not own`（actions.log，05:06:40 起持续至 15:39:49 共多轮，与我探针时刻吻合）；
  4. 防双载设计要求切相到 omlx 前先释放 mtplx → 释放被拒 → **所有 omlx 相派发（OCR/翻译）自 05:06 起全部被拒**（fail-closed，AGG25-P0-2③ 设计行为）；mtplx 相（初稿/摘要）不受影响（15:26:21 ensure A18 verified）。
- 影响面：本轮（第2轮）若派发涉及语料准入（OCR）或参考翻译链（含 20261004a 忠实度门重设计的批量确认测试），将被此环境冲突阻断。8001 本身健康且 GLM-OCR-bf16 与翻译模型均在驻留列表中——数据路径无问题，纯粹是仲裁器无法切相。
- 本管理员不可处置：杀 1759 违反"模型服务器只经编排器管理"红线且属用户自有应用；改产品代码超出本岗（ask 明确只配环境）；编排器无 adopt/强放端点（main.py 全部 model-lifecycle 端点仅 status 一个）。→ 已升级主会话裁决。
- 共存实测：本轮无法执行（被上述阻断）；第1轮（2026-10-03）实测记录见 `../ocr_rebind_20260929/mem_probe.md`（共存无互斥卸载）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→100（第1轮测试较昨日 91 新增 9，正常）。
- ego-browser（space 37，用后即关）：打开 5186 →"请选择项目（共100个）"（UI=API）→ 点"新建项目"→ 对话框"新建医学写作项目"打开，建项方式/试验药物/适应症/研究分期四要素俱全 → 点"取消"不提交 → 对话框 0 残留、UI/API 均 100、零新建。
- 证据：`smoke_r2_home_snapshot.txt`、`smoke_r2_dialog_open_snapshot.txt`、`smoke_r2_dialog_closed_snapshot.txt`。

## 红线自检
未碰 live 8910（本轮未探测到 8910 监听，亦未发起任何请求）/医学监查/共享 runtime；模型服务器只经编排器（探针走产品 API，拒绝手动杀 1759）；未清库未删历史；未改产品代码；未动用户自有 MTPLX.app 及其服务器。
