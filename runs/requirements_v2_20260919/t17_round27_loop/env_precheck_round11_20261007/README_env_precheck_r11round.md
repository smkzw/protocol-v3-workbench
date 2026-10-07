# 环境预检与清洁 · 第11轮证据（2026-10-07 18:42–18:57 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 9202（18:18:27 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 6663（18:14:07 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-a0d262b6350b9b5c`（ready=true、missing=[]）；HEAD=0400c3dd（18:16:18，≥f72fa95）。
- 编排器：status=ok；mtplx owned=true（pid 13471）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过
- ego-browser：id 114（并行线昨夜遗留）已被其属主收尾；现存 3 个 agent 空间 id 142/143/144 均为今午新建 **R24 医学监查验收批**（并行线，B/A/C 三轨）→ 全部保留并上报。本子系统测试者空间残留 0；用户空间 0；headless 残留 0。
- 【实现师知悉·持续上报】后端未提交漂移仍在（同4文件，10-04/10-05 遗留）+ 2 个未跟踪前端测试文件；指纹从同一盘上源码树计算，两侧一致性不受影响。建议尽快收编。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=477 / failed=219 / cancelled=11 / **非终态=0**（无卡死无悬置，运维帽无适用对象）。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 52 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（428.2s=排队+切相+冷加载）→ 翻译探针 **passed 268ms**（{"status":"ok"}）→ OCR 热复测 **passed 97ms**；8001 双模型同驻（co_resident=true）、RSS 33,919,824 KB 稳定。
- 证据：`ocr_probe_visual_r11_1.json`、`translation_probe_r11.json`、`ocr_probe_visual_r11_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（第11轮节）。跨相等待 428s 属既知 P2。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→143（第10轮测试较 140 新增 3，正常）。
- ego-browser（用后即关）：5186 打开"共143个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 143 零新建。
- 证据：`smoke_r11_home_snapshot.txt`、`smoke_r11_dialog_open_snapshot.txt`、`smoke_r11_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用与并行线空间。
