# 环境预检与清洁 · 第6轮证据（2026-10-06 10:42–10:53 CEST，环境管理员，本ask内实跑）

## ① 四端健康 — 通过
- 前端 5186：HTTP 200；vite pid 93025（10:07:31 起），进程环境实测 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`；经代理 `/api/health`=ok。
- 后端 5301：pid 92982（10:07:29 起），`/api/health`→ok。
- 构建指纹：两侧一致 `api-c6c1b2ca9863fd24`（ready=true、missing=[]）；HEAD=2556332（10:08:08，≥f72fa95；提交晚于后端启动39秒但改动已在盘，指纹一致为证）。
- 编排器：status=ok；mtplx owned=true（pid 913）；omlx 健康 idle；队列空。

## ② 测试者环境隔离 — 通过（含处置裁定说明）
- ego-browser 4 个 agent 空间，**全部判定为活动中工作区、未关闭**：
  - id 54 "入排1001V1连续验收"——并行监查线（历轮先例：其属主自管自清）；
  - id 82/83/84 "R20B medical monitoring acceptance / R20-A MX循R20A-RUX browser acceptance / R20-C-medical-director"——第5轮检查（04:41）时尚不存在、10:07 栈重启后新出现的 A/B/C 三轨浏览器验收批，标签页均指向本工作台 5186。疑似并行线/实现师正在进行的验收批；误杀在跑验收的代价远大于留置，故全部保留并上报，若确认为孤儿遗留由下轮或属主收尾。
- 用户自有空间 0；headless 残留 0。

## ③ 上轮缓存清理 — 通过（零删除）
- 临时垃圾扫描 0 命中。

## ④ durable 无卡死任务 — 通过
- completed=405 / failed=188 / cancelled=4 / **非终态=0**（第5轮的2条running已正常收尾）。

## ⑤ OCR 环境侧清偿 — 全序列通过
- 缺口重读在册（retest_r26.md OCR key 行）；PADDLE key 复核（文件 0/进程 0）仍不存在，维持裁决路线；绑定 revision 37 ocr=`ocr_local_omlx/GLM-OCR-bf16` enabled+whitelisted、备份在。
- 实测：OCR 探针 #1 **passed**（397.3s=排队+切相+冷加载；上轮 memory_guard 竞态未再现）→ 翻译探针 **passed 264ms**（{"status":"ok"}）→ OCR 热复测 **passed 96ms**；8001 双模型同驻（co_resident=true）、RSS 33,932,592 KB 稳定。
- 证据：`ocr_probe_visual_r6_1.json`、`translation_probe_r6.json`、`ocr_probe_visual_r6_2.json`；已记 `../ocr_rebind_20260929/mem_probe.md`（2026-10-06 第6轮节）。
- 跨相等待 397s 属既知 P2 设计行为（测试者遇等待勿误报故障）。

## ⑥ 新场景冒烟 — 通过
- 基线 `GET /api/projects`→126（第5轮测试较 122 新增 4，正常）。
- ego-browser（用后即关）：5186 打开"共126个"（UI=API）→新建项目对话框 6/6 要素 → 取消不提交 → 0 残留、UI/API 均 126 零新建。
- 证据：`smoke_r6_home_snapshot.txt`、`smoke_r6_dialog_open_snapshot.txt`、`smoke_r6_dialog_closed_snapshot.txt`。

## 红线自检
未碰 8910/医学监查/共享 runtime；模型服务器只经编排器；未清库未删历史；未改产品代码；未动用户应用；本轮未关闭任何他人/疑似在用空间（仅自行冒烟空间用后即关）。
