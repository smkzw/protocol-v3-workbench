# Protocol v3 Fork Continuation Implementation Plan
> Execution: follow current user authority and latest platform workflow. Fork owner is gpt-5.6-sol:medium. Delegation follows actual bounded benefit and current manifest, not a fixed team.

**Goal:** 完成可实际使用的Ⅱ/Ⅲ期双入口医学写作产品，并以真实文档/研究证据完成验收。
**Architecture:** 保留当前React/FastAPI/SQLite/图运行/GenOffice；修复候选→事实→DOCX→核对的断缝，不新建竞争主库。
**Baseline:** SOURCE_STATE.json + 当前dirty核对 + HANDOVER_STATUS，不是旧GitHEAD单独一项。

## 计划与状态分工
本Plan/TASK_INDEX.json是任务**定义与依赖**；Trellis是唯一动态执行状态。旧requirements-v2/tasks.json保留PLAN_ONLY不回填假完成。当前Trellis主任务09-21-protocol-v3-t17-round11可继续引用F编号，在需要独立状态时由现有task.py创建子任务，不重新init项目。
状态采用planned/in_progress/implemented/verified/needs_user_decision；任务代码完成不等于产品已验收。当前资料包完成也不标产品Goal complete。

## 顺序
| ID | 交付 | 依赖 | 重点 |
|---|---|---|---|
| F00 | 无损接管与源码/环境锚定 | 无 | 先读移交，不重复派发design worker |
| F01 | 设计真实选项、确认与原意图恢复 | F00 | 接收本轮worker而非重做 |
| F02 | 给药补答→已确认事实闭环 | F01 | 解决用户重复补答不推进 |
| F03 | 整稿及设计任务的真实恢复 | F00 | 保留完成章、失败隔离、真实出口 |
| F04 | 双入口/来源/实际模型身份对账 | F00 | 不伪造来源；legacy与v3归一 |
| F05 | 有实质内容的完整工作初稿 | F02,F03,F04 | 缺口是显式对象，不是空标题 |
| F06 | 当前Word、候选、缓冲、历史闭环 | F00 | 本轮已有大量修复，定向补齐 |
| F07 | 绑定实际Word快照的显式核对 | F06 | 不能复用旧语义稿冒充核对 |
| F08 | Word对象局部AI与重生成 | F05,F07 | 锚点/范围/冲突/撤销 |
| F09 | 文献选择插入、编号与文献表 | F04,F06 | 引用≠fact_path≠表格REF |
| F10 | 模板/Word格式/文控与输出保真 | F05,F06 | 有本轮修复，不重写人工稿 |
| F11 | 全状态宽屏产品体验收口 | F01,F02,F05,F06,F07,F08,F09 | 真实UI、输入、提示、导航 |
| F12 | 独立跨研究端到端及医学/Word验收 | F03,F04,F05,F07,F08,F09,F10,F11 | 差异化2+1盲测；接受范围分层 |
| F13 | 可重现交付、复盘、激活选择 | F12 | 不自动生产切换或清理证据 |

每项有 tasks/Fxx_EXECUTION.md 与 Fxx_ACCEPTANCE.md。具体步骤、允许文件、测试命令、反例和交付字段在那里，不用在多个文档重写。

## 建议实际推进次序
F00→接收F01在途结果→F02；同时可交给独立有界worker核查F03或F04（文件无重叠才并行）。主owner先闭合资料→确认→初稿，再完成F06→F07→F08/F09→F10→F11→F12→F13。不要先做一轮全站重装修，再回到无法起草的链路。
F03已有源码修复不代表真实案例已通；F06已有快照闭环不代表所有IME/断网组合已通。查既有证据，有效则复用，只有输入/工件变化才补受影响验证。

## 交付证据递增，非阶段暂停
F00–F11按依赖连续实现与源码核查，完成记implemented即可继续；F12集中执行完整测试和产品验收。不得把依赖“已实现”误写成“须先完成该任务全部运行测试”。构建中的最小诊断仅在真实阻塞且源码检查不足，或完整功能批次必须编译后才能继续集成时使用，记录原因。测试命令是验收目录，不是逐步骤执行清单。详见 [BUILD_DISCIPLINE](BUILD_DISCIPLINE.md)。
发现问题先定位和修复；不存在阻塞就继续构建，不每改一处跑一次测试/构建/浏览器回归。
只有Ⅰ期模板、真实项目切换/生产激活、来源无法裁决的重大科学决定、用户选定第三方文献互操作目标才提问；独立可做工作继续。

## 范围控制
不把本包扩展为医学监查、共享工作台迁移、密钥轮换或安全工程。源数据只读、历史保留。模板规范升级以新版本显式记录，不删负向样本、xfail或强行改expected掩盖问题。审阅者建议不自动成为业务义务；owner须按证据裁决。

## 产品完成定义
A01–A26各有结论及证据层级，V01–V08桌面体验达标；至少两个差异研究+一个保留盲测完成关键路径；实际Word保存/重开/下载与当前研究/文档身份对应；医学内容充分性与关键差异经有依据的独立核查；未选专项清楚排除，未通过项不藏。发布/真实cutover另获用户批准。
