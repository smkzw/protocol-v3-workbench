# 环境预检与清洁 · 第4轮证据（2026-10-05 22:35–22:45 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 94258（22:13:24 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 93239（22:08:37 起），`/api/health`→ok。
- 构建指纹：5186 `/runtime-build.json` 期望 `api-e0ab48b753b5d5b1` == 后端自报同值（ready=true、missing=[]）；HEAD=1b4c756（2026-10-05 22:08:34 "fix(protocol-v3): P0-1 final — _insert_event replay tolerance…"，≥f72fa95，早于后端启动3秒，已生效）。
- 编排器：status=ok；mtplx healthy+resident（owned=true，pid 96259，编排器自有）；omlx healthy 非驻留（idle）；队列空。

## ② 测试者环境隔离 — 通过
- ego-browser：本子系统残留空间 id 66 "SMOKE r3-2 finish 678" →已 `finish({keep:[]})` 关闭；id 54 "入排1001V1连续验收"（并行监查线）→沿用先例保留并上报；用户自有空间 0。
- headless/测试浏览器残留进程：0。

## ③ 上轮缓存清理 — 通过（零删除）
- `find t17_round27_loop`（.DS_Store/*.tmp/*.pyc/__pycache__/*~/*.swp）→ 0 命中。

## ④ durable 无卡死任务 — 通过（2个running为活跃非卡死）
- `durable_mw_jobs`：completed=365 / failed=177 / cancelled=4 / **running=2**。
- running 2 条详情：`mwjob_23ab90e6…`（research_pipeline）与 `mwjob_793b49f4…`（competitor_triage），均 2026-10-05T20:17:02Z 创建、updated_at 与查询时刻同一秒（实时心跳）、lease_expires_at 在未来10分钟——**活跃任务**（第3轮收尾全链自检在跑），非卡死泄漏。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读：retest_r26.md OCR key 行在册；PADDLE key 复核（密钥文件 0、运行进程 0）仍不存在，维持主会话裁决路线。
- 绑定核验：revision 31，ocr=`ocr_local_omlx/GLM-OCR-bf16`（enabled，specialized_whitelisted）；备份 `.pre-ocr-rebind-20260928` 仍在；绑定随 22:08 后端启动已生效。
- 实测序列（经产品 API）：OCR 探针 #1 **passed**（349.2s=排队等mtplx最小驻留+切相+GLM-OCR冷加载，读码成功）→ 翻译探针（dawncr0w）**passed 323ms**（{"status":"ok"}）→ OCR 探针 #2（翻译后热复测）**passed 106ms**；8001 双模型同驻（co_resident=true），RSS 33,923,088 KB 稳定。证据：`ocr_probe_visual_r4_1.json`、`translation_probe_r4.json`、`ocr_probe_visual_r4_2.json`；已记入 `../ocr_rebind_20260929/mem_probe.md`（2026-10-05 第4轮节）。
- 【供任务书参考】跨相任务仍可能遇 3–6 分钟排队（本轮实测 349s，与④的在跑自检任务互斥所致，属既知 P2 设计行为）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→118（第3轮测试较 114 新增 4，正常）。
- ego-browser（用后即关）：打开 5186 →"请选择项目（共118个）"（UI=API）→"新建项目"对话框打开，6 要素（新建医学写作项目/建项方式/试验药物/适应症/研究分期/创建并进入写作）全命中 → 取消不提交 → 对话框 0 残留、UI/API 均 118、零新建。
- 证据：`smoke_r4_home_snapshot.txt`、`smoke_r4_dialog_open_snapshot.txt`、`smoke_r4_dialog_closed_snapshot.txt`。

## 红线自检
未碰 live 8910/医学监查/共享 runtime；模型服务器只经编排器（探针全走产品 API）；未清库未删历史（缓存清理零删除、durable 只读查询）；未改产品代码；未动用户应用与并行线空间。
