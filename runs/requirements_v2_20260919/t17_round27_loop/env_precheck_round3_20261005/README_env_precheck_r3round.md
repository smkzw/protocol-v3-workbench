# 环境预检与清洁 · 第3轮证据（2026-10-05 16:36–16:52 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 47426（16:19:36 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`、`--host 127.0.0.1 --port 5186 --strictPort`；经代理 `/api/health`=ok。
- 后端 5301：pid 47374（16:19:21 起），`/api/health`→ok。
- 构建指纹：5186 `/runtime-build.json` 期望 `api-3cff0a9dbea26912` == 后端自报 `api-3cff0a9dbea26912`（ready=true、missing=[]）；HEAD=a1268ca（2026-10-05 12:03，≥f72fa95，早于后端启动，无需重启）。
- 编排器：status=ok；**8002 阻断解除**——用户旧 MTPLXApp（pid 1203）已不在，16:33:37 编排器自己拉起 mtplx（pid 50555，owned=true，父进程=5301 后端）；8001（pid 2264）健康；仲裁队列空。

## ② 测试者环境隔离 — 通过
- ego-browser：2 个 agent 空间——id 55 "SMOKE-r3-2 chain verification"（本子系统残留）→已 `finish({keep:[]})` 关闭；id 54 "入排1001V1连续验收"（**并行监查线**的空间，非本子系统遗留，沿用第2轮先例不处置）→保留并上报。用户自有空间 0。
- headless/测试浏览器残留进程：0。

## ③ 上轮缓存清理 — 通过（零删除）
- `find t17_round27_loop`（.DS_Store/*.tmp/*.pyc/__pycache__/*~/*.swp）→ 0 命中；第2轮后新增全为证据/日志/规格档。

## ④ durable 无卡死任务 — 通过
- `durable_mw_jobs`：completed=349 / failed=172 / cancelled=4 / **非终态=0**（较第2轮 287/150/1 为第2轮测试正常增量）。

## ⑤ OCR 环境侧清偿 — 全序列通过（阻断解除）
- 缺口重读：retest_r26.md:68（"OCR API Key is not configured for the Paddle provider（0/4）"）。
- 密钥复核：密钥文件 PADDLE 0 命中、运行中 5301（pid 47374）进程 0 命中——维持主会话裁决路线。
- 绑定核验：revision 27，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；备份 `.pre-ocr-rebind-20260928` 仍在；绑定随 16:19 后端启动已生效，无需重启。
- 实测序列（经产品 API）：OCR 视觉探针 #1 **passed 125ms** → 翻译探针（dawncr0w，{"status":"ok"}）**passed 275ms** → OCR 探针 #2（翻译后热复测）**passed 99ms**；8001 双模型同驻（GLM-OCR-bf16+dawncr0w 同时在 /v1/models），RSS ~33.9GB 稳定。证据：`ocr_probe_visual_r3_1.json`、`translation_probe_r3.json`、`ocr_probe_visual_r3_2.json`；已记入 `../ocr_rebind_20260929/mem_probe.md`（2026-10-05 节）。
- 过程附注（如实记录）：首探针 16:38:19 恰逢 mtplx 最小驻留窗口，排队 317s 后 16:43:36 放行（客户端 300s 超时中断了首次 HTTP，但服务端完成了切相）；放行后编排器停 mtplx、oMLX 相就位，全部探针亚秒级通过。该跨相等待属既知 P2 设计行为（客户端耐心 vs 服务端队列，历轮已立案），非本轮环境异常——**测试者跨相操作（初稿→语料翻译）可能遇 5–10 分钟等待，属已知现象**。
- DIAN标记文件 `../DIAG/env_blocker_8002_20261004.md` 所述阻断已自然解除（用户侧关闭应用），未做任何越权处置。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→114（第2轮测试较 100 新增 14，正常增量）。
- ego-browser（space 58，用后即关）：打开 5186 →"请选择项目（共114个）"（UI=API）→ 点"新建项目"→ 对话框"新建医学写作项目"打开，建项方式/试验药物/适应症/研究分期四要素+取消/创建并进入写作按钮俱全 → 点"取消"不提交 → 对话框 0 残留、UI/API 均 114、零新建。
- 证据：`smoke_r3_home_snapshot.txt`、`smoke_r3_dialog_open_snapshot.txt`、`smoke_r3_dialog_closed_snapshot.txt`。

## 红线自检
未碰 live 8910/医学监查/共享 runtime；模型服务器只经编排器（探针全走产品 API；8002 的恢复是编排器自身行为，我只读观测）；未清库未删历史（缓存清理零删除）；未改产品代码；未动用户 MTPLX.app（旧应用进程已由用户侧自行退出，与主会话裁定路径一致）。
