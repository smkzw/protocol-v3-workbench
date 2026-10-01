# Round27 立案与证据补录（2026-09-28，第26轮复盘·修订第1轮落地）

立案人：实现师（本批修复的同一轮）。本文档把第25轮复测遗留的两条 P2 预警
正式立案——它们就是第26轮 ENV-02（入口B解析32分钟）的先兆，在档案里躺了一天
未立案；同时把第25轮 T4/T5 测试者截图补入证据库。

## 一、正式立案：两条 P2 预警（ENV-02 先兆）

来源：`t17_round25_loop/retest_round1.md` §二.3（P2 观察）与 §三（压测 P2 观察）。

### P2-A：写作 UI 无排队/等待位提示（前端未接 P1-7 状态端点）

- 原文（retest_round1.md §三）：「持有方被持续同相真实负载占满时，跨阶段队头会
  长时间等待（本次 900s 客户端先行放弃）……排队期间写作 UI 没有任何
  "你在排队/第几位"的提示——P1-7 的状态端点已具备，前端未接。」
- 现状（本轮修复后）：
  - 方案摘要导入（入口B）的等待面板已接 `/api/model-lifecycle/status`
    （`MedicalWritingSynopsisProjectIntake.jsx`，8 秒轮询，如实显示
    "模型正被N个任务占用，另有M项在排队/模型服务空闲"，取不到状态则不显示）。
  - 其余写作界面（语料检索、翻译等）的排队提示仍未接——**维持立案，P2，
    归下一轮实现批**。状态端点本身已在线（AGG25-P1-7，
    `services/api/app/main.py` `GET /api/model-lifecycle/status`）。

### P2-B：客户端超时 < 服务端队列超时（断开后服务端占位至超时）

- 原文（retest_round1.md §三）：「translation 请求排队 900s 后被客户端超时
  （status -1 TimeoutError）；期间仲裁器未报错，其 1800s phase_queue_timeout
  阀值未到……客户端断开后服务端排队项仍占位至超时，属已知代价，建议实现师
  评估对客户端断开的感知取消。」
- 现状：本轮 ENV-02 预算层把受影响最重的任务类
  （protocol_synopsis_structuring）单请求窗提至 1200s、梯子总预算 1800s
  （`ai_execution_policy.py` TASK_TYPE_ROUTE_* + `ai_gateway.py` ladder
  budget），并新增 `provider_ladder_budget_exhausted` 显式失败码；但
  **客户端断开感知取消未实现，其余任务类的超时/预算未分级——维持立案，P2，
  归下一轮实现批**。
- 本轮新增先兆记录：ENV-02 修复把入口B最长等待从"无界×3"收敛为
  "1200s×预算内"，仍可能长于浏览器侧等待耐心；等待面板的可取消性（已具备）
  与取消后抢救（本轮已实现）是配套出路。

## 二、T4/T5 截图证据入库（第25轮，复盘建议补录）

原始位置：`t17_round25_loop/T4/`、`t17_round25_loop/T5/`（本轮复制留档至
`t17_round27_loop/evidence/R25_T4|T5/`，原件未动）。

- R25_T4（医学写作视角，9 张）：01 导入解析_模型地址未批准告警、02 导入解析
  失败_第二次、03 AI提取运行中_有进度提示、04 第5次导入快速失败、05 翻译AI
  设置当前值、06 默认选中无权项目_看板503降级、07 切换可读项目后看板恢复、
  08 v2新文件提取挂起超10分钟、09 v2最终失败_8002已在线仍报地址未批准。
  ——对应第25轮 T4-01/02/04/06/08/09 缺陷证据（AGG25-P0-2、P1-6 链路）。
- R25_T5（药物警戒视角，12 张）：01 新建项目对话框、02 写作工作区_版本门放行、
  03 竞品处理抽屉、04 语料准备_5条件未满足、05 缺陷_例外放行
  stale_revision_conflict、07 缺陷_建议采用失败_prefill_package_stale、08 单
  字段修改视图、09 事实提交中、10 下游失效确认、11 语料例外放行、12 方案首页
  与编辑器、13 章节骨架_安全性评价待补齐。
  ——其中 **05 号截图（stale_revision_conflict）即 AGG-P0-03（例外放行版本
  竞态＋勾选丢失）的第25轮现场证据**，本轮已修（反例：后端
  `test_override_corpus_gate_survives_benign_concurrent_revision_bump`、前端
  `MedicalWritingAuthoringJourneySetup.overrideAck.test.jsx`）；07 号即
  AGG25-P1-5 预填缺陷现场，第25轮已修。

## 三、vite 默认代理挂账（未修，继续挂账）

`frontend/vite.config.mjs:8` 默认代理仍硬编码 `http://127.0.0.1:8910`——本轮
未动该文件（单一集成人纪律，避免与在途工作流缓存冲突）。任何人启动前端仍必须
显式 `VITE_API_PROXY_TARGET=http://127.0.0.1:5301`。高危脚枪原样在案。

## 五、全量门收尾对账（最终门 run_2026-09-28T155357Z_66417，snapshot 16:22Z）

- failed 43 = **存量账本内 42**（`tools/acceptance/known_failures_0926v1.json`
  453 条账目内，属"带已知账目通过"口径）+ **1 例 HEAD 存量 flake**：
  `test_medical_writing_word_verification_repository.py::
  test_repository_same_key_concurrency_writes_one_receipt`——6线程并发写
  断言对时序敏感，与本轮改动无关（该文件与基线零差异；实测 5 连跑
  4过1挂，两头皆出现过）。
- **本轮引入的新失败 = 0**。pyflakes 账本外新项 = []；eslint noundef = 0；
  自检 A002/A003/A004/fingerprint/layout 全 PASS；required nodes 无缺失。
- 上一门（151803Z）的 2 例账本外失败（前端测试清单计数）已通过三处钉扎
  同步修复，本门复跑确认消失（test_frontend_check_wrapper 17/17）。

## 四、本轮顺手修正的测试基建问题（非缺陷清单内）

1. `frontend/src/runtimeReadiness.test.js` → `.test.jsx`：上一工作流的 WIP
   测试文件后缀不在测试清单注册表里（`frontend/tests/protocol_v3_test_inventory.mjs`
   只认 `.test.jsx/.test.mjs`），导致官方配方 `npm run test:unit:vitest` 直接
   报 "unknown runner" 无法收口。内容本就是 vitest/jsdom 测试（第25轮复测即
   以 vitest 运行），改名后纳入清单，3/3 通过。
2. `medicalMonitoringProjectNeutralContract.test.mjs` 守卫正则补 `srv`：
   该测试（HEAD 上的存量红，非本轮引入）的对抗自检清单要求守卫必须拒绝
   `/srv/...` 本地绝对路径，但守卫正则只覆盖 `Users|private|tmp`——守卫落后
   于自己的对抗清单。补齐后 node 清单 66/66 全绿（生产文件扫描仍零命中）。
3. 前端测试清单计数钉扎同步（三处）：`toolchain_manifest.json` 的
   test_inventory（counts/vitest_paths/paths_sha256）与
   `verify_toolchain_rebuild.py` 的 `FRONTEND_INVENTORY_COUNTS`/
   `FRONTEND_TEST_PATHS_SHA256`/`FRONTEND_VITEST_PATHS` 全部同步到真实现状
   68/20/48。此前已 stale：WIP 批新增 4 个 vitest 测试文件未登记，全量门
   `test_frontend_check_wrapper` 2 例因此报新失败；同步后该文件 17/17
   两次复跑全绿。
4. `services/api/app/ai_task_runner.py` 补 `import hashlib`：`:1032` 处
   已使用未导入（历史提交 10dd453 引入的真 NameError 雷）；门静态检查
   pyflakes 同步清零该项。`services/api/app/main.py:1621` 的未定义 `Dict`
   （历史提交 355563 引入）改为 `dict`，门静态检查新项清零。
