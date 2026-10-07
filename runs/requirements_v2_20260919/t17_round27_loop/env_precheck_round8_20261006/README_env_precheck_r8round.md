# 环境预检与清洁 · 第8轮证据（2026-10-06 23:49–2026-10-07 00:02 CEST，环境管理员，本ask内实跑；本轮=运行上限轮）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 42449（23:31:27 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 41168（23:28:27 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-d42ee24227847a19`（ready=true、missing=[]）；HEAD=1dfde82e（23:29:55，≥f72fa95；提交在后端启动后88秒，但改动已在盘、指纹一致为证）。
- 编排器：status=ok；mtplx owned=true（pid 43960）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过（全部为他线基础设施，未触碰）
- ego-browser 3 个 agent 空间，均属并行监查线域：id 54 "入排1001V1连续验收"（历轮先例）、id 114 "1006V1入排交付窗口"、id 116 "R21B 医学监查子系统验收测试"（今夜 23 点后新建，疑似其夜班验收批）→ 全部保留并上报；本子系统测试者空间残留 0；用户自有空间 0。
- headless 进程 9 个=**单一 Chrome-for-Testing 树**（root pid 37895，23:04:38 起，puppeteer 通道），父进程为 pi-harness 的 `__omp_worker_daemon_broker`（pid 34777，22:38 起）——omp/pi 外部测试座基础设施，非本子系统测试者残留 → 不碰、上报（20261006c 本轮外部云测试者不参与，但该 daemon 属 harness 常驻，其去留由主会话/属主决定）。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=444 / failed=209 / cancelled=6 / **非终态=0**（cancelled 4→6 为第7轮运维帽在环内正常行使；无卡死无悬置，无需 cancel）。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 43 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（452.3s=排队+切相+冷加载，无 memory_guard 误拒）→ 翻译探针 **passed 262ms**（{"status":"ok"}）→ OCR 热复测 **passed 96ms**；8001 双模型同驻（co_resident=true）、RSS 33,924,752 KB 稳定。
- 证据：`ocr_probe_visual_r8_1.json`、`translation_probe_r8.json`、`ocr_probe_visual_r8_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（第8轮节）。跨相等待 452s 属既知 P2。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→135（第7轮测试较 132 新增 3，正常）。
- ego-browser（用后即关）：5186 打开"共135个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 135 零新建。
- 证据：`smoke_r8_home_snapshot.txt`、`smoke_r8_dialog_open_snapshot.txt`、`smoke_r8_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用、并行线空间与 omp-harness 进程；运维帽无适用对象（无卡死/悬置/已离场遗留任务）。
