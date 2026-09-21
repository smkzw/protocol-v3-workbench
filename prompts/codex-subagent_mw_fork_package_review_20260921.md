# 独立资料包审阅合同
模式conference：用户明确要求执行会商，包将直接指导另一个模型持续实现，需独立判断是否遗漏关键需求或造成逐改测试/过度设计。父任务此时负责文件清单/hash/源码overlay/交接资料校验，与你的语义审阅不重复。

唯一工作区：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313
冻结待审文档目录：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_fork_execution_20260921
先读最新全局AGENTS及适用项目指令；其后按下列范围只读，不修改任何文件（包括个人plan），不启动子agent/服务/浏览器/模型/产品测试，不读HANDOFF_ROUND10.md（含key）。
先读00_START_HERE、01_STATE_AND_HISTORY、02_AUTHORITY_AND_MATERIALS、03_PRD、04_ARCHITECTURE_DESIGN、05_IMPLEMENTATION_PLAN、06_EXECUTION_RULES、07_ACCEPTANCE_PLAN、08_FORK_PROMPT.txt、GOAL_PROMPT.txt、BUILD_DISCIPLINE、09_DECISIONS_AND_RISKS、CLINICAL_CONTENT_CONTRACT、TASK_INDEX.json、evidence/HANDOVER_STATUS.md。再读全部14执行+14验收包（只读），必要比对原始reviews/protocol-v3-requirements-v2/{REQUIREMENTS_AMENDMENT,ACCEPTANCE,AGENT_NEXT_TASK}.md。
SOURCE_STATE/SOURCE_MAP/AUTHORITY_MANIFEST/source_overlay已生成；父任务正在补PACKAGE_MANIFEST和10_REVIEW_AND_RELEASE，因此不要把仅这些收尾文件尚未完成当语义缺陷。

当前用户补充：严格约束过度设计、构建过程测试，禁止“改1处测1次”。F00–F11连续实现，F12集中验收，构建仅必要阻塞诊断/完整批次集成所需最小编译。不要建议每个F任务独立跑一轮测试。既有Task17测试报告是历史事实，不是未来逐改要求。

请独立检查：
1 需求R1–R5/A01–26与新宽屏/信息密度/真实Office/科学选择是否完整；是否误把重要未完成能力排除或把待验工作写成完成。
2 14包依赖能否连续实现；是否有测试/会商硬门或过度抽象、无必要体系。
3 同目录fork/dirty源码、旧Goal、未决worker终态、当前模型/凭证/现场隔离是否表达准确；不需要你读取任何含秘密文件。
4 最新F01已知后端忽略选择、NI字段不符、样本量planned_n、旧回执revision等是否具体可执行；允许只读实际三个相关源确认。
5 对会阻碍接手或误导建设的具体缺陷给文件:行+最小修订；非必要建议明确optional，不扩scope。

输出完整中文报告到最终消息，父任务保存。包括已读source、P1/P2具体发现/证据/修订、矛盾无证据写未验证、不声称产品验收。无需额外管理节点，不执行产品测试。模型/effort按派发元数据，不自己猜测effective模型。
