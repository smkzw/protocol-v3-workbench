# 环境预检与清洁 · 第12轮证据（2026-10-07 21:22–21:34 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 9202（18:18:27 起，与第11轮同进程未重启），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 6663（18:14:07 起，同前未重启），`/api/health`→ok。
- 构建指纹：两侧一致 `api-a0d262b6350b9b5c`（ready=true、missing=[]，与第11轮相同）；HEAD 推进至 a1b6609d（20:43:04，**纯文档提交**：LOOP收敛定稿 CLOSURE_REPORT + P1-53 修订门规格归档——不动源码故指纹不变，≥f72fa95）。
- 编排器：status=ok；mtplx owned=true（pid 44151，本日第3次自动换新属正常最小驻留轮换）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过
- ego-browser：第11轮的 R24 A/C 两空间已被属主收尾；现存 2 个 agent 空间 id 142 "R24B 医学监查子系统验收"（并行线在用）与 id 147 "入排1006V1正式入口验证"（并行监查线域）→ 全部保留并上报；本子系统测试者空间残留 0；用户空间 0；headless 残留 0。
- 【实现师知悉·持续上报】后端未提交漂移同4文件+2个未跟踪前端测试文件仍在（10-04/10-05 遗留未收编）；指纹从同一盘上源码树计算，两侧一致性不受影响。a1b6609d 未收编它们。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=484 / failed=220 / cancelled=13 / **非终态=0**（cancelled 11→13 为环内运维帽正常行使；无卡死无悬置）。

## ⑤ OCR 环境侧清偿 — 全序列通过（含一次取证自纠）
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 52 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：探针 #1 首发请求 **HTTP 200**（112.9s 排队+切相+冷加载，本轮等待明显短于近几轮的400s+）但因本管理员先建目录漏步导致响应文件未落盘——补建目录后热态重跑取证 **passed 136ms** → 翻译探针 **passed 315ms**（{"status":"ok"}）→ OCR 热复测 **passed 110ms**；8001 双模型同驻（co_resident=true）、RSS 33,916,528 KB 稳定。（如实说明：首次200的响应体内 visual_probe 证据未留存，以热态重跑的完整证据链替代，判定依据不变——HTTP 200 即读码成功的强口径。）
- 证据：`ocr_probe_visual_r12_1.json`、`translation_probe_r12.json`、`ocr_probe_visual_r12_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（第12轮节）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→145（第11轮测试较 143 新增 2，正常）。
- ego-browser（用后即关）：5186 打开"共145个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 145 零新建。
- 证据：`smoke_r12_home_snapshot.txt`、`smoke_r12_dialog_open_snapshot.txt`、`smoke_r12_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用与并行线空间。
