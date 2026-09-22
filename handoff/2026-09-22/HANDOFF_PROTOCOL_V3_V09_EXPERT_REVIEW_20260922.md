# Protocol v3 v0.9 专家审阅交接文档

日期：2026-09-22 14:34 CST
工作区：`/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`
分支：`main`
本批起点：`a6244fa2412fe7c912429f10beb259596c8d53f4`
最终提交：包含本文档的 GitHub `main` HEAD；接手时以 `git rev-parse HEAD` 与 `git status --short --branch` 实测为准。

## 0. 给接手 Agent/专家的一页结论

本阶段完成了 Study A 全文初稿生成器从 v0.5 到 v0.9 的连续修复、真实产品模型运行和多轮独立医学审阅。最新冻结候选是 v0.9：

- job：`mwjob_bb370670e7bc8936451212fd`
- schema：`protocol_full_draft_artifact_v9`
- SHA-256：`d1e5ad959fd5cdce693e86f072ae39fff9a4056d1601320b86061bfa9d216820`
- 产品模型：`opencode-go/deepseek-v4.1-flash:max`
- 85/85 节；44 complete、1 decision_required、40 source_gap；2 张决定卡；1 个统计 required；22 个 AI run。
- 节级证据引用 264 条，持久来源绑定 104 条。

v0.9 **不得采纳、不得写入 Word、不得描述为可申报成品**。它的研究事实数字稳定，已经关闭 v0.5 的 73 张重复卡、SUSAR 乱定义、决定正文预写和字段错绑，但 fresh 医学会商仍判定 `REVISE`：安全性采集起点、估计目标跨章措辞、体格检查终点、公司语料转项目义务四类问题必须先修复。

下一安全动作是先让专家审阅本 handoff、v0.9 冻结工件与会商报告；专家意见收敛后实现 v0.10 生成规则，重新生成一次全文并做 fresh 医学会商。不要重复上游检索、分诊、下载、OCR、翻译，不要重派已完成的 v0.9 job。

## 1. 产品目标与当前 Goal

产品面向懒惰、视觉敏感、不熟悉计算机和 AI 的资深医学写作人员。目标不是让用户操作工作流，而是让 AI：

1. 理解已有材料并区分项目事实、公司语料和缺失资料；
2. 给出少量可回答、可预选的专业选项；
3. 写出有实质内容、证据可追溯的完整初稿；
4. 只在主要终点、估计目标、样本量、对照、剂量等真正高影响事项上要求人审；
5. 让用户以点选和少量修改得到格式规范、可进入申报审核流程的 Word。

当前 Goal 仍为 active。其权威全文由 Codex Goal 系统保存，核心执行入口是：

- `plans/protocol_v3_fork_execution_20260921/00_START_HERE.md`
- `plans/protocol_v3_fork_execution_20260921/03_PRD.md`
- `plans/protocol_v3_fork_execution_20260921/CLINICAL_CONTENT_CONTRACT.md`
- `plans/protocol_v3_fork_execution_20260921/04_ARCHITECTURE_DESIGN.md`
- `plans/protocol_v3_fork_execution_20260921/05_IMPLEMENTATION_PLAN.md`
- `plans/protocol_v3_fork_execution_20260921/06_EXECUTION_RULES.md`
- `plans/protocol_v3_fork_execution_20260921/07_ACCEPTANCE_PLAN.md`
- `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`

重要用户决定：持续构建但本阶段完成后交专家审阅；构建过程避免“改一处测一次”，以完整功能批集中测试；工程会商长轮询 120 分钟，不因几分钟无输出重派；默认产品模型严格为 `opencode-go/deepseek-v4.1-flash:max`；公司/共享语料不得冒充本项目事实；未确认的医学实施规则应明确成缺口，不能用通用段落凑字数。

## 2. 本阶段来龙去脉

### 2.1 v0.5：证据链可持久化，但医学质量不合格

提交 `58639c7` 和 `a6244fa` 解决全文分批生成后的 evidence span 持久化、跨批短 ID、损坏最终件恢复和 read-time adoption 验证。真实 v0.5 候选 85/85 节、23 complete、49 decision_required、13 source_gap、73 张决定卡。独立医学会商发现：推荐项被提前写进正文、同一问题重复成卡、估计目标混用、SUSAR 定义错误、fact_path 语义错绑。v0.5 未采纳。

### 2.2 v0.7：决定卡显著减少，但模型把缺失规则写成 complete

v0.6 的确定性降级过宽，形成 47 个空缺口，因此未作为主要审阅基线。v0.7 缩窄降级规则，真实候选 75 complete、3 decision_required、7 source_gap、4 张决定卡、469 条节级证据引用。fresh Grok 4.7 医学会商发现三套安全窗、由访视推断检查日程、DLQI 时点冲突、伴侣妊娠/新生儿规则，以及 21 个空 required 节。v0.7 未采纳。

### 2.3 v0.8：关闭多项推断，但统计升级和状态判断退步

v0.8 真实候选 70 complete、3 decision_required、12 source_gap、4 张卡、407 条证据引用。它关闭了三套安全窗、DLQI 冲突时点、伴侣妊娠/新生儿推断和 21 个空 required 壳。fresh 会商仍发现：统计升级消失；§1 概要被误判 source gap，§2.1 背景反而误标 complete；AE 定义和盲态人员被自行写入；CMS-D017 公司语料仍绑定本项目；合并用药卡与未定义救援治疗冲突。v0.8 未采纳。

### 2.4 v0.9：事实和缺口显著更诚实，但仍不是用户成品

v0.9 将可写决定字段收窄到探索性目的/终点，探索性卡加入“不设置”；缺项目来源的运营规则改为 source gap；概要用已确认事实成文；统计混用恢复唯一升级；决定正文在确认前严格为空。

产品身份探针通过，声明和实际均为 `opencode-go/deepseek-v4.1-flash`，role thinking 为 max。job 单 attempt 生成 22 批，约 57 分钟完成，无 fallback。owner 脚本与 fresh Grok 4.7 会商共同核验 85/85。

## 3. 当前代码改动的含义

### `services/api/app/medical_writing_full_draft.py`

- prompt/artifact/chunk/descriptor 升到 v0.9/v9/v9/v10，v3–v8 保留只读。
- 决定字段只允许 `picos.exploratory_objectives` 和 `picos.exploratory_endpoints`。
- 仅把仍为 missing/deferred 的字段交给生成器；同一字段只允许一个指定章节承载。
- `decision_required` 在用户确认前正文必须为空；确认后沿既有 StudyDefinition writer 持久化并只重生成受影响章节。
- 高影响事实复述改为 advisory；§9 的“复合策略”触发唯一 required 统计升级。
- 提示词禁止由访视日、排除标准和终点名称推导安全性检查、TEAE 窗、DLQI 时点、妊娠规则、研究结束或盲态人员。

### `services/api/app/ai_task_runner.py`

- 持久化前核验 evidence source、locator、quote；删除悬空证据。
- 因证据删除而失去支持的 complete 节降为 source gap，不补造文字。
- decision_required 归一化时清空预确认正文。
- 仅对明确、具体、无来源的实施规则做确定性降级，避免 v0.6 的过度降级。

### `services/api/app/ai_gateway.py`

- 允许当前 chunk 没有可写决定字段。
- source_gap 和 decision_required 的正文必须为空；complete 才必须有实质正文。
- 同一节不允许重复使用同一 fact_path。

### `services/api/app/ai_execution_policy.py`

- 服务端全文 prompt 版本升为 `protocol_full_draft_v0_9`。

### 测试

- 证据归一化、损坏最终件重建、空决定路径、决定 owner、重复路径、预确认正文、schema 只读和决定局部重生成都有对应测试。
- `tests/protocol_v3/test_draft_marker_context.py` 的旧阶段断言已升为当前 schema 与真实 evidence 合同；它仍验证合法研究实施句不会被误认成写作占位符。

## 4. v0.9 冻结工件与审阅证据

### 冻结工件

- 本地运行时原件：`runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_bb370670e7bc8936451212fd/full-draft.json`
- GitHub 专家审阅副本：同一路径仅显式提交该 JSON；同目录数据库、chunk 和运行日志不提交。
- SHA-256：`d1e5ad959fd5cdce693e86f072ae39fff9a4056d1601320b86061bfa9d216820`

### 最重要的审阅文件

- v0.9 外部医学报告：`runs/conference/mw_r11_v09_medical_review_20260922/evidence_single_object.md`
- v0.9 owner 裁决：`reviews/codex_conference_mw_r11_v09_medical_review_20260922_review.md`
- v0.9 metrics：`metrics/mw_r11_v09_medical_review_20260922_conference_metrics.md`
- v0.9 阶段记录：`runs/requirements_v2_20260919/t17_round11/STUDY_A_FULL_DRAFT_V09_MEDICAL_REVIEW_20260922.md`
- v0.8 对照报告：`runs/conference/mw_r11_v08_medical_review_20260922/evidence_single_object.md`
- v0.7 对照报告：`runs/conference/mw_r11_v07_medical_review_20260922/evidence_single_object.md`
- v0.5 对照报告：`runs/conference/mw_r11_v05_medical_review_20260922/evidence_single_object.md`

## 5. v0.9 已完成和未完成

### 已完成

- 85 个目标章节与 85 个候选章节一一对应。
- 数字事实与 StudyDefinition r8 一致：100 mg QD、16 周、1:1、访视、终点、132 例等未发现第二套冲突。
- §1 概要已用确认事实形成实质正文。
- 40 个真实资料缺口正文为空，不再以通用文字冒充完成。
- 探索性目的/终点只绑定匹配字段，并提供“不设置”推荐。
- §9 保留唯一统计升级，不恢复 21 个空红节。
- v0.5 的 73 张卡、SUSAR 错误定义、决定正文预写、错误 fact_path 已关闭。

### 未完成，专家应重点审阅

1. **安全性采集起点**：§9.5 写“自第1天起采集”，项目事实没有采集起点。
2. **估计目标**：源事实本身混用“治疗策略人群”和停药/救援按“复合策略”判无应答；§3.1 又改写为“估计目标采用治疗策略”，§2.4 省略复合策略。不得由医学写作层私自选一种。
3. **体格检查**：§7.3.1 将体格检查写入安全性终点；确认终点只含实验室、生命体征和 12 导联心电图。
4. **公司语料边界**：§10.3、§11.3、§11.4、§12.1–§12.4、§12.7 把公司方案参考句写成本项目程序，并与父节 source gap 冲突。
5. **探索性卡原子性**：两张卡可交叉选择，目的与终点可能不配对，应合并为一张原子卡。
6. **较小措辞**：§4.5“约24周”、§10“签署知情同意后进入筛选”、组名和“系统/全身暴露”需统一。
7. **尚未做**：v0.10、浏览器验收、采纳、Word 合并、原生 Word 保存重开、Study B/C 完整旅程、最终 F12/F13。

## 6. 专家审阅建议问题

请专家明确回答以下问题，不必重做工程审阅：

1. 估计目标原句应保留原文待统计修订，还是当前即可确定为复合策略？医学写作层默认不改。
2. 关键次要终点是否需要在同一统计升级中明确多重性尚未规定？当前建议是需要。
3. 公司方案语料可否直接成为本项目监查、稽查、培训、偏离和保密义务？当前默认不可，除非有本项目文件确认。
4. 探索性目的/终点是否默认“不设置”？当前推荐是“不设置”。
5. 救援治疗和提前停药后的随访是否继续作为资料缺口，而不是新增设计卡？当前推荐继续作为缺口。

## 7. 下一阶段 v0.10 执行包

按以下顺序做，不增加额外框架：

1. 在 prompt 和确定性归一化中禁止无来源的“自第1天起采集”、体格检查终点和公司语料项目义务。
2. 把估计目标四个相关章节绑定到同一个统计决定；未决时整组不可采纳。保留原句，不由生成器改写策略名称。
3. 将探索性目的/终点改成一个原子选择，推荐“不设置”；若选早期 PASI 75，同时写入目的和终点。
4. 修正 §4.5、§10、组名和暴露术语。
5. 升版 prompt/artifact/chunk/descriptor，集中运行受影响测试一次。
6. 重启隔离 5299，身份探针通过后创建新 logical work key；不要重用或重派 v0.9 job。
7. 生成 v0.10，核验 85/85、证据链、卡片原子性和唯一统计升级。
8. fresh 医学会商通过后才可进入 ego(lite) 浏览器审阅和 Word 路径。

## 8. 验证证据

最终集中命令：

```bash
PYTHONPATH=services/api:packages:tests:. \
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -q \
  tests/test_medical_writing_full_draft.py \
  tests/test_ai_task_runner.py \
  tests/test_ai_execution_policy.py \
  tests/protocol_v3/test_draft_marker_context.py
```

结果：`106 passed`。Python `py_compile` 和 `git diff --check` 通过。两次前置测试失败均属于测试命令/旧阶段 fixture 迁移：第一次缺少 `tests` PYTHONPATH；第二次旧 fixture 未提供当前 schema/证据链。最终测试使用真实当前工件合同，不降低产品门控。

会商 review gate：v0.8 与 v0.9 均 `ok=true`。

## 9. 运行状态与红线

- 本任务启动的隔离 5299 已停止，没有在途产品 job 或会商。
- live 8910 仍由 PID 43371 监听，未触碰。
- 共享 live workbench、医学监查子系统、SOP 原件和 `plan-upgrade-20260905` 未修改。
- 产品密钥只从 `~/.omp/agent/.env` 进入内存，没有写入提交文件、prompt、checkpoint 或日志。
- 三个已存在的 `runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime/ai_*.json*` dirty 文件属于旧共享测试运行状态，本批未提交、未重置。
- 不要 `git add .`，不要 reset/clean；显式添加本 handoff 列出的源码、测试、审阅文件与 v0.9 单个冻结 JSON。

## 10. Git 与恢复步骤

接手时执行：

```bash
cd /Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313
git fetch origin
git status --short --branch
git log -3 --oneline --decorate
shasum -a 256 runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_bb370670e7bc8936451212fd/full-draft.json
```

预期：`main` 与 `origin/main` 同步；冻结 JSON 哈希为 `d1e5ad…6820`；除已知三个共享 runtime dirty 文件和历史未跟踪运行目录外，不应有本阶段源码未提交改动。

阅读顺序：本文 → v0.9 owner review → v0.9 外部医学报告 → v0.9 冻结 JSON → v0.8/v0.7 报告（仅做演进对照）→ Trellis checkpoint。

## 11. 经验教训

- “卡少”不等于用户负担低；空 required 可以消失，但同一科学冲突必须保留一个真正可处理的入口。
- prompt 约束无法完全阻止模型把公司语料写成项目规则，必须有来源类型感知的确定性验证。
- complete/source_gap 的准确性比表面覆盖率更重要。v0.9 从 70 complete 降到 44 complete 是质量改善，不是退步。
- 章节级决定卡不适合承载跨字段原子决定；探索性目的和终点应一起确认。
- 长模型任务应保持同一 durable job 等待。v0.9 用约 57 分钟完成，期间没有因为短时无输出停止、重派或换模型。
- 扩展测试时必须使用完整项目 PYTHONPATH；旧阶段 fixture 要随 schema 合同升版，不能借此降低真实产品门控。
