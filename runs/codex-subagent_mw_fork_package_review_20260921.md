**审阅结论：资料包已覆盖主要产品义务，依赖图可支持连续实现；建议修正 1 项 P1、4 项 P2 后交付。** 问题集中在少数验收措辞、执行时机和 F01 修复合同，不需要重写架构、增加管理节点或安排逐任务测试。

本次仅作资料包语义审阅及三个相关源码的定向核查。未修改文件，未运行产品测试、服务、浏览器或模型，未读取 `HANDOFF_ROUND10.md`；不构成产品验收。审阅模型及 effort 由父任务派发元数据记录，本报告不推测 effective 身份。

以下文件定位均以[冻结资料包目录](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921>)为基准。

**已读资料**

- 最新全局 `AGENTS.md`、实施区 `AGENTS.md`、`frontend/AGENTS.md`；补读 `.trellis/workflow.md` 的适用覆盖规则及 `.trellis/spec/protocol-v3.md`。
- `00_START_HERE` 至 `09_DECISIONS_AND_RISKS`、`GOAL_PROMPT.txt`、`BUILD_DISCIPLINE.md`、`CLINICAL_CONTENT_CONTRACT.md`、`TASK_INDEX.json`、`evidence/HANDOVER_STATUS.md`。
- F00–F13 全部 **14 个执行包＋14 个验收包**。
- 原始 `REQUIREMENTS_AMENDMENT.md`、`ACCEPTANCE.md`、`AGENT_NEXT_TASK.md`。
- 定向源码：`DesignElementsCards.jsx`、`agent2/design_adoption.py`、`api/design.py` 中相关完整定义。

文件清单、hash、overlay 完整性属于父任务检查范围；未将 `PACKAGE_MANIFEST`、`10_REVIEW_AND_RELEASE` 的收尾状态列为缺陷。

**P1：无期中研究的验收措辞错误排除了样本量 alpha**

证据：[07_ACCEPTANCE_PLAN.md:49](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/07_ACCEPTANCE_PLAN.md:49>)要求至少一个“优效无期中”研究，并“验证不索要NI/alpha”。

这里未限定 alpha 属于期中分析，容易驱动实施者取消样本量卡的 alpha 输入、确认或验证。包内 `CLINICAL_CONTENT_CONTRACT.md:20` 明确保留样本量 alpha/power；实际 `_sample_size_writer` 也在 `design_adoption.py:58–62` 保存 alpha。这是包内直接冲突。

最小修订：

> 至少一个优效且无期中分析的研究，不要求非劣效界值及期中分析专属的 alpha 消耗／分配确认；样本量计算所需 alpha 等假设仍按适用合同保留。

不增加新科学要求，只消除错误的排除范围。

**P2：统一模板把接管检查推迟到 F12，同时部分执行步骤又要求提前运行验收**

证据：

- [F00_EXECUTION.md:18](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/tasks/F00_EXECUTION.md:18>)要求接管时检查 HEAD、dirty、运行状态；但第30–41行又把 `git status`、HEAD、资料包校验、当前任务查询统一规定为“留待F12”。
- `F03_EXECUTION.md:28、44`仍直接要求故障运行验证、HTTP通过后运行真实模型案例。
- `F10_EXECUTION.md:24–26`直接列实际 Word验证；`F11_EXECUTION.md:26–27`直接列 ego操作与点击计数，没有在这些步骤本身注明 F12 执行。
- `F13_ACCEPTANCE.md:3、20、22`仍称“F12集中执行”、最后执行F12；但 F13 明确依赖 F12，交付工件尚未生成时无法在此前验收。

全局 `BUILD_DISCIPLINE` 已明确覆盖，因此这不是实际存在的强制逐改测试政策；但执行模型逐包加载时仍可能被局部指令误导。

最小修订：

1. F00注明：“接管所需只读身份、源码和资料包检查立即执行，不属于产品运行测试。”
2. F03/F10/F11上述步骤改为“实现相应能力；以下运行证据在F12取得”，下一步直接指向依赖已实现的任务。
3. F13验收改为“F13交付时核对交付资料；仅产品改动或证据漂移才回到F12受影响范围”。

不增加任何测试轮次。

**P2：F01选择身份修复没有明确要求同步修改恢复查询及兼容旧回执**

证据：[F01_EXECUTION.md:28](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/tasks/F01_EXECUTION.md:28>)已经正确指出 writer 忽略选择、decision只有整卡哈希。但源码中身份算法有两个独立落点：

- `agent2/design_adoption.py:259–273`：创建决定，option哈希使用 `[run_id, output_sha, card]`。
- `api/design.py:490–514`：恢复查询重新构造同一决定，也使用不含选择的整卡哈希。

若实施者只修改 writer和创建侧哈希，恢复查询可能继续构造旧身份；历史未决操作如何恢复也没有明确规则。这直接关联 F01 的“原operation恢复、零重复采用”目标。

最小修订，在第28行后补一句：

> 选择身份的生成、adopt前回执查询及recover必须采用一致规则；保留旧操作与旧回执的可恢复解释，不重写历史。旧记录无法证明所选项时显示未知，不推断第0项。

在 F01验收补入“新选择操作恢复”和“旧版操作恢复”两个场景，**统一留到F12执行**，无需新增身份框架或迁移体系。

**P2：F01已定位清单遗漏两个直接影响关键科学确认的源码分支**

现有 F01验收主要检查第二选项、回执恢复及逐卡人审，尚未明确下面两个反例：

1. `design_adoption.py:229`使用  
   `primary_endpoint_confirmed is not True and not ep.get('text')`。  
   只要proposal终点有文字，该校验分支就不会拒绝缺失或为假的确认标记。正常前端目前发送 `true`，但后端确认合同本身不足。
2. `design_adoption.py:154–175`称未知适用性应“可见但不可采用”，实际 NI／期中卡却在未发现明确否定时加入可采用列表；前端 `DesignElementsCards.jsx:393–397`也只依据proposal是否存在显示条件卡。

这两点是源码事实；是否还有其他层阻止最终落盘，**本次未验证**，不能据此直接声称已有真实错误采用。

最小修订：

在 [F01_EXECUTION.md:27](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/tasks/F01_EXECUTION.md:27>)的已定位断缝中增加：

> 核对后端是否真正要求主要终点明确确认；条件卡适用性未知不得仅因proposal存在而视为已满足采用前提，沿既有事实与确认链处理。

F01验收补两个反例：“终点确认标记缺失／false”“条件适用性未知”。属于既有高风险确认和三态需求，不扩大范围，也不要求立即测试。

**P2：F01仍把已解释的历史路由审计失败列成必须退出0的检查**

证据：

- [F01_EXECUTION.md:45](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921/tasks/F01_EXECUTION.md:45>)列出旧任务的 `audit-execution`，第47行统一要求“退出0”。
- `evidence/HANDOVER_STATUS.md:8`已经说明该审计退出1来自当前路由与历史初始化路线的元数据匹配问题，并明确“不篡改历史让审计变绿”“不当作产品停工门”。

前者可能使接手者反复审计历史任务，甚至修订历史上下文以获得绿灯。

最小修订：

将该命令标为“历史审计定位参考，不要求重跑或退出0”；F01接管只核对已有终态、实际最终执行身份、产物和剩余缺陷。新的派发才遵守新的审计合同。

**其余审阅结论**

| 检查范围 | 结论 |
|---|---|
| R1–R5／A01–A26 | 文档级覆盖完整；没有发现把基础引用、局部AI、当前Office核对、完整初稿等重要未完成能力排除出范围。 |
| 宽屏、信息密度、真实Office | PRD与V01–V08保留了宽屏双栏、字体底线、真实交互、同iframe专注及当前版本身份要求。 |
| 任务依赖 | TASK_INDEX与实施Plan一致，无依赖环；F12依赖经传递覆盖F00–F11，可按implemented继续构建。 |
| 过度设计 | 未发现必须新建数据库、队列、编辑器或通用引擎的要求。Office投影针对实际核对断缝，有当前消费者；仍应执行包内最小必要性限制。 |
| 会商硬门 | 总规则不要求14次会商；各包引用最新AGENTS触发条件，可合并冻结范围审阅。F01的独立复核应在集中验收中安排，不作为进入F02的前置。 |
| fork／dirty | 同目录保留dirty、父任务停止写入、新worktree不得假定复制dirty、overlay先比较再整合，表达准确。 |
| 旧Goal | 明确仍是旧paused记录，资料包不冒称修改Goal或启动fork。 |
| worker终态 | 最新移交文件明确已终态，旧“在途”措辞由其覆盖；终态和fallback身份本次仅作文件一致性审阅，未独立核验运行回执。 |
| 产品模型／凭证／现场 | 工程模型与产品模型区分清楚，实际产品身份保留未验证；禁复制密钥启动配方，现场与隔离运行边界明确。 |

F01列出的五个既有问题均有合理落点：全部候选被写入、NI字段名不一致、writer未写`planned_n`、404恢复缺少可继续出口、旧回执可能降低前端revision。尤其 `planned_n` 已要求追踪canonical路径和消费者，而不是机械增加字段，这一约束应保留；本次只确认该writer未写入，**未确认下游是否存在独立推导**。

没有必要另开重规划、重构或预验收阶段。上述修订可在现有文件内完成，保持 **F00–F11连续实现、F12集中验收、F13交付核对**。