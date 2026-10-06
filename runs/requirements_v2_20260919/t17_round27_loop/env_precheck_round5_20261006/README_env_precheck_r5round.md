# 环境预检与清洁 · 第5轮证据（2026-10-06 04:41–04:57 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 46233（04:10:40 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 46041（04:08:57 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-b6e6a88df2e261a0`（ready=true、missing=[]）；HEAD=f37b64e（04:10:26 NEW-P0-19/L2 分诊-撰写死锁修复，≥f72fa95）——提交虽晚于后端启动3分钟，但改动已在盘（工作树对 services/api 无未提交漂移，指纹一致为证）。
- 编排器：status=ok；mtplx owned=true（pid 50082）；omlx 健康。
- 【如实上报·实现师知悉】存在未提交前端漂移（App.jsx/SynopsisProjectIntake/errorContract.mjs+/runtimeReadiness 等7文件，最新mtime为昨日22:02，近6.5小时无新改动——非进行中编辑，5186当前运行的即该盘上状态）；建议实现师在合适节点收编提交。

## ② 测试者环境隔离 — 通过
- ego-browser：本子系统无遗留空间（第4轮冒烟空间已自关）；并行监查线空间 id 54 沿用先例保留并上报；用户自有空间 0；headless 残留 0。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中（.DS_Store/*.tmp/*.pyc/__pycache__/*~/*.swp）。

## ④ durable 无卡死任务 — 通过（2个running为活跃）
- completed=384 / failed=183 / cancelled=4 / running=2：
  - `mwjob_c99782ef…`（protocol_full_draft，00:45Z 创建，已跑约2小时）：updated_at 与查询同秒、租约有效——长任务心跳续租，非卡死；
  - `mwjob_c12ad4ee…`（competitor_triage，02:20Z 创建）：心跳同秒、租约有效——活跃。

## ⑤ OCR 环境侧清偿 — 通过（含一次自愈型竞态记录）
- 缺口重读（retest_r26.md OCR key 行在册）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 34 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：探针 #1 排队 541s 获切相（mtplx 被 SIGTERM 正常释放）后 **memory_guard 同秒三连拒**（`26.13GB < 34.375GB`，评估时 mtplx ~30GB 尚未回收）→ 502；**立即重试即 passed**（系统 128GB/89% 空闲，7.76s 含冷加载）→ 翻译探针 passed 315ms（{"status":"ok"}）→ OCR 热复测 passed 108ms；8001 双模型同驻（co_resident=true），RSS 33,921,568 KB 稳定。
- 【产品侧观察项·记录不修】内存守卫与"刚停服务器内存未回收"存在时序竞态（同一秒内三拒、无退避重评），自愈型（重试即过）；跨相排队 541s 属既知 P2。测试者若遇偶发 502，重试即可，勿直接判产品故障。
- 证据：`ocr_probe_visual_r5_1.json`（502 原始响应）、`ocr_probe_visual_r5_1retry.json`、`translation_probe_r5.json`、`ocr_probe_visual_r5_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-06 第5轮节）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→122（第4轮测试较 118 新增 4，正常）。
- ego-browser（用后即关）：5186 打开"共122个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 122 零新建。
- 证据：`smoke_r5_home_snapshot.txt`、`smoke_r5_dialog_open_snapshot.txt`、`smoke_r5_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器（探针全走产品 API，mtplx 的停止与 oMLX 的加载均为编排器自身行为）；未清库未删历史；未改产品代码；未动用户应用与并行线空间。
