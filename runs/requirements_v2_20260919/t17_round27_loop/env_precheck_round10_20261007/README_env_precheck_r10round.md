# 环境预检与清洁 · 第10轮证据（2026-10-07 10:39–10:53 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 12165（10:18:43 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 9992（10:14:23 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-1d7ffba5bc080b99`（ready=true、missing=[]）；HEAD=0ddfb758（10:15:38，≥f72fa95）。
- 编排器：status=ok；mtplx owned=true（pid 14623）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过
- ego-browser：仅剩 id 114 "1006V1入排交付窗口"（并行监查线昨夜遗留，先例保留并上报）；第9轮的 R22 A/B/C/D 四空间已被其属主自行收尾。本子系统测试者空间残留 0；用户空间 0；headless 残留 0。
- 【实现师知悉·再次上报】后端未提交漂移仍在（同4文件：ai_task_runner/synopsis_import/writing_reference_repository/writing_reference_translation_batch，10-04/10-05 遗留），另有 2 个未跟踪前端反例测试文件（CorpusGate.overrideDeadlock.test.jsx / MedicalWritingAuthoringJourneySetup.impactStaleRecovery.test.jsx）；指纹从同一盘上源码树计算，两侧一致性不受影响。建议尽快收编。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=462 / failed=215 / cancelled=10 / **非终态=0**（cancelled 8→10 为环内运维帽正常行使；无卡死无悬置）。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 49 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（412.5s=排队+切相+冷加载，无 memory_guard 误拒）→ 翻译探针 **passed 309ms**（{"status":"ok"}）→ OCR 热复测 **passed 107ms**；8001 双模型同驻（co_resident=true）、RSS 33,924,496 KB 稳定。
- 证据：`ocr_probe_visual_r10_1.json`、`translation_probe_r10.json`、`ocr_probe_visual_r10_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（第10轮节）。跨相等待 412s 属既知 P2。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→140（第9轮测试较 138 新增 2，正常）。
- ego-browser（用后即关）：5186 打开"共140个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 140 零新建。
- 证据：`smoke_r10_home_snapshot.txt`、`smoke_r10_dialog_open_snapshot.txt`、`smoke_r10_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用与并行线空间；运维帽无适用对象（无卡死/悬置/已离场遗留任务）。
