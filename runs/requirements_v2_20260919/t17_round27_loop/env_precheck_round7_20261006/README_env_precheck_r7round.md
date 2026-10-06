# 环境预检与清洁 · 第7轮证据（2026-10-06 17:31–17:46 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 55905（16:51:41 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 54835（16:47:13 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-bad24bbc68545255`（ready=true、missing=[]）；HEAD=06d0b4f（16:50:16，≥f72fa95；提交在后端启动后3分钟，但改动已在盘、指纹一致为证）。
- 编排器：status=ok；mtplx owned=true（pid 31831，检查时 inflight=1——有活跃派发）；omlx 健康 idle；队列含2个 translation@omlx 等待者（与在跑流水线一致）。

## ② 测试者环境隔离 — 通过
- ego-browser：仅剩 id 54（并行监查线，先例保留）。第6轮的 R20 A/B/C 三空间**已被其属主自行收尾**（上轮"活动工作区"判断得到验证）。用户空间 0；headless 残留 0（过程中出现1个瞬时headless进程，复查消失，非测试残留）。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过（运维帽执行说明）
- completed=430 / failed=198 / cancelled=4 / running=1：
  - `mwjob_5f1bc319…`（protocol_full_draft，14:59:26Z 创建）——**心跳实时**（updated_at 距查询5秒）、租约有效至 15:41Z、创建于 14:47Z 后端重启之后、与 mtplx inflight=1 活跃派发吻合 → 判定为进行中的收尾/验证任务，**非卡死非遗留，未行使 cancel**（运维帽只停"证据已够/已离场/卡死悬置"，本条不属此类）。
- 若后续发现心跳死亡/租约过期的悬置 job：按用户指令 20261006 立即 `POST /jobs/{id}/cancel`。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 39 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（墙钟 359.6s=排队+切相+冷加载，当时 mtplx 相有活跃流水线）→ 翻译探针 **passed 281ms**（{"status":"ok"}）→ OCR 热复测 **passed 103ms**；8001 双模型同驻（co_resident=true）、RSS 33,919,760 KB 稳定。
- 【计量口径观察项】探针#1响应内 `elapsed_ms=1266594`（21min）与墙钟 359.6s 不符——该计时跨网关 lease 排队预算累计、疑含在跑流水线的共享门等待；passed 结论不受影响（读码成功才有200）。记录供实现师参考，不深究。
- 证据：`ocr_probe_visual_r7_1.json`、`translation_probe_r7.json`、`ocr_probe_visual_r7_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-06 第7轮节）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→132（第6轮测试较 126 新增 6，正常）。
- ego-browser（用后即关）：5186 打开"共132个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 132 零新建。
- 证据：`smoke_r7_home_snapshot.txt`、`smoke_r7_dialog_open_snapshot.txt`、`smoke_r7_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器（探针全走产品 API；运维帽未越界使用——无卡死/悬置任务可停）；未清库未删历史；未改产品代码；未动用户应用与并行线空间。
