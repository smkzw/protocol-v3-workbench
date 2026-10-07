# 环境预检与清洁 · 第9轮证据（2026-10-07 07:52–08:06 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 78271（07:33:05 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 75529（07:28:27 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-7f8b42dc398c29fa`（ready=true、missing=[]）；HEAD=18ed698b（07:30:46，样本量门/自主背景规格补充，≥f72fa95）。
- 编排器：status=ok；mtplx owned=true（pid 81160）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过（他线基础设施未触碰）
- ego-browser 5 个 agent 空间，均属并行监查线域：id 114 "1006V1入排交付窗口"（昨夜遗留，其属主未收）；id 127/128/129/130 为今晨新建 R22 A/B/C/D 四轨验收批（医学监查线）→ 全部保留并上报；本子系统测试者空间残留 0；用户空间 0；headless 残留 0。
- 【实现师知悉】存在**未提交后端漂移**：`services/api/app/ai_task_runner.py`（10-05 16:09）、`medical_writing_synopsis_import.py`（10-05 21:54）、`writing_reference_repository.py`（10-04 20:34）、`writing_reference_translation_batch.py`（10-05 22:00）——均 2 天前遗留未收编、非进行中编辑；指纹从同一盘上源码树计算，两侧一致性不受影响（运行中后端即当前盘上状态）。建议实现师尽快收编提交，避免后续轮次指纹基线混乱。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=453 / failed=211 / cancelled=8 / **非终态=0**（cancelled 6→8 为环内运维帽正常行使；无卡死无悬置）。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 46 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（425.5s=排队+切相+冷加载，无 memory_guard 误拒）→ 翻译探针 **passed 284ms**（{"status":"ok"}）→ OCR 热复测 **passed 102ms**；8001 双模型同驻（co_resident=true）、RSS 33,921,824 KB 稳定。
- 证据：`ocr_probe_visual_r9_1.json`、`translation_probe_r9.json`、`ocr_probe_visual_r9_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（第9轮节）。跨相等待 425s 属既知 P2。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→138（第8轮测试较 135 新增 3，正常）。
- ego-browser（用后即关）：5186 打开"共138个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 138 零新建。
- 证据：`smoke_r9_home_snapshot.txt`、`smoke_r9_dialog_open_snapshot.txt`、`smoke_r9_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用与并行线空间；运维帽无适用对象（无卡死/悬置/已离场遗留任务）。
