# R2-D wave2 live notes

session: loop27-r2-d
tester: R2-D
landing: 2026-10-04 23:52:58
intended project: R2D-W2-CKDaP-KOR228
entry B label: 导入方案摘要 / 导入并提取
no independent project name: true

## M2 parse
- click 导入并提取: 2026-10-04 23:56:43
- 23:57:00 UI: AI正在提取… 1/1 块, 模型被3个任务占用
- ~00:00 dialog vanished; no R2D in list
- 00:00:41 reopen recovered: 已运行4分钟 / 已恢复上次提取
- 00:11:27 FAIL1: chunk 0 validation failed: protocol synopsis non-default value requires source evidence at framing.version (~14.7 min)
- 00:11:42 继续处理 → 第2次解析尝试
- 00:42:38 FAIL2: 解析未完成：模型本次响应超时…繁忙，不是故障 (~31 min this attempt, ~46 min wall)

## bypass 从零开始
- drug R2D-W2-CKDaP-KOR228 / indication 慢性肾病相关瘙痒 / II期
- create failed twice: idempotency_key string_too_short JSON

## M1 clicks (approx)
新建项目 5; 导入方案摘要 4; 挂文件 4; 导入并提取 3; 继续处理 1; 从零开始 1; 创建并进入写作 3; 取消 1
no batch/auto-release screens reached

## observations
- no login
- first landing = other project R26MW-SGC2101 medical writing
- version banner, no 重新检查
- internal ids: mwcell_greenfield_*, mtplx-flash-next-optimized-speed
- camofox_click 30s timeout; used JS click / REST upload+click
- camofox tabs vanished several times; recover via new tab + 新建项目
