# HANDOFF — R11 修复批收尾（2026-09-23，无损暂停点）

## 给下一窗口的一句话
R11 两条 P0 已根因闭环并修复推送（2c0f52b 分诊冻结 + 0bc92fb 入口A死路），**但 live 环境还在跑旧代码**——先重启服务，再做迷你验证测试，然后 P1 批 → 删旧项目 → 派第十二轮。

## 状态快照
| 项 | 状态 |
|---|---|
| HEAD / 已推送 | 0bc92fb（前：2c0f52b P0-A；07b6164 R11报告归档） |
| R11 报告 | 4/4 归档 + R11_AGGREGATE.md（runs/requirements_v2_20260919/t17_round11/） |
| P0-A 分诊冻结 | 已修（create_run 防覆盖 + 终态落盘 + 回归测试） |
| P0-B 入口A死路 | 已修（路由拒绝大白话化 + 死路按钮隐藏 + 测试） |
| P1 批 | 未动 |
| 第十二轮 | 未派 |
| live 5301 后端 | 健康 200，**旧代码**（无 --reload） |
| live 5186 前端 | 健康 200，**旧构建** |
| MTPLX 8002 | 健康，profile 已是 8002 rev 3 |
| 本批测试 | 后端 triage+pipeline 105/105、triage 全表面 563+42、前端 113/113 |

## 下窗口第一步（照做即可）
```bash
# 1. 重启后端（旧进程 PID 会变，先找再杀）
lsof -nP -iTCP:5301 -sTCP:LISTEN          # 找 PID
kill <PID>
cd <ROOT> && PYTHONPATH=services/api:. setsid nohup python3.14 -m uvicorn app.main:app \
  --host 127.0.0.1 --port 5301 \
  >> /tmp/wp6_backend_5301.log 2>&1 &      # WORKBENCH_RUNTIME_DIR 等环境变量按既往启动脚本
# 2. 重建前端（按既往 5186 构建流程）
# 3. 健康检查：5301/5186/20128/8002 全 200
```
注意：启动命令的运行时目录环境变量以既往轮次启动脚本为准（runs/requirements_v2_20260919/wp6_0922v2_20260922/ 下有 isolated_runtime）。

## 然后按 LOOP 走
1. Ego 迷你验证：COPD 从零链（建项目→检索→分诊完成或部分失败可恢复→框架解锁）+ 入口A新文案验证。
2. P1 批：分诊标记三按钮 disabled 无原因；文献手动确认与 DOI 耦合无说明；文献卡卷期页来源可疑。
3. 备份后删旧项目（保留出厂 demo）→ 重派第十二轮（muse-spark COPD / gemini MS / grok MDD / deepseek 膝OA，thinking 档位不变）。
4. 测试期间超长静默纪律不变；严格 UI 黑盒；不直连后端/DB。

## 关键技术锚点（给后来者省时间）
- run_id 确定性：`ct_run_{canonical_input_hash[:20]}`；同输入重放 = 同 run_id → create_run 现在复用不覆盖（medical_writing_competitor_triage.py，搜 "Deterministic re-entry"）。
- executor 终态现在无条件 `store_triage_run`（搜 "terminal status"）。
- 父对账：research_pipeline.py `_triage_review_ready_at_deadline`（partial_failed 会给出"仅部分完成"诚实报错，重试走 retry-triage 端点 8960 行）。
- intake 路由拒绝分类：MedicalWritingSynopsisProjectIntake.jsx `synopsisJobErrorKind`。
- 测试运行：后端 `PYTHONPATH=services/api:. python3.14 -m pytest ...`（python3.14 用户库有 cryptography+pytest）；前端 `npm run test:unit:vitest`（勿裸跑 vitest，会丢 jsdom）。

## 红线提醒（不变）
不触碰 live 8910 / 医学监查 / 共享 runtime；不删历史 immutable rows/runs/logs/evidence；所有构建修订同步 GitHub 提交；测试全程 UI 黑盒。
