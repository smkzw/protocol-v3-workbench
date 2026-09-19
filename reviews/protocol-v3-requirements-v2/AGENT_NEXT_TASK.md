# 可直接交给实施 Agent 的任务指令

仓库：https://github.com/smkzw/protocol-v3-workbench
审阅基线：dd2018e0aa7da0176066cedccdf2075f9ec57eb4
GenOffice 架构参考基线：316ded6f0a39235fec8d21c068d8a0766ee6172b

## 1. 当前任务与边界

先阅读本包 REQUIREMENTS_AMENDMENT.md 和当前仓库规格，再检查 git status、HEAD 和用户未提交修改。若实际 HEAD 不同，报告差异并重验受影响文件；不得强制重置到本基线。隔离分支实施，不覆盖用户修改，不推送上游、不发布公共包、不自动切换生产。

把医学写作工作台实现为“两入口共享研究设计 → 关键确认 → AI完整工作稿 → Office自由编辑 → 显式核对”。本次用户已明确 R1–R5，不再追问这些决定。

不以修复编辑器为由重构其他医学子系统，不新建第二套项目/事实/任务数据库。不删除历史回执和测试证据，不把旧字段意义无版本地改变。

## 2. 先修需求冲突，不要先美化编辑器

### P0：通用性和污染范围

审阅 chapter_facts.py 的 RESIDUAL_RECOMMENDATIONS、MODIFICATION_WATCH、predicate_corrections，以及相邻 prompt、配置和导出器。定位案例值如何进入生产路径。

先编写跨疾病/药物/分期/来源反例。移除无适用性边界的案例决策，保留通用序列化和规则。模型仅能给建议，不能用“常规”伪装特定产品条件。不得靠改测试期望让错误通过。

存量审查先只读：按来源、决策事件和原模板绑定查找疑似受影响记录。仅相同数值不足以判定污染。不得自动删除旧 facts、修改旧事件或重写全部稿件；形成明确的新修订/核对项，保留原稿。

### P1：准备度与草稿合同

同时改造 ManuscriptWorkspace.jsx、manuscript_plan.py、manuscript_request.py、chapter_draft.py 及其字段绑定/候选校验路径。

不得仅把按钮 disabled 去掉、把 all_applicable_inputs_ready 永远设 true，或抓住校验异常继续生成。

引入有版本的草稿准备视图：critical_design_confirmed、blocking_design_conflicts、can_generate_working_draft、open_gaps、chapter_dispositions。现有完整合同保留在适合的质量/发布检查阶段。根据现有事实目录和真实研究依赖划分，禁止硬编码一套所有研究必须具备的巨大关键集。

从零写作不能要求先伪造 source ID 或上传无意义文件；有用户设计、无附件时，输入材料仍应有真实的用户输入身份及版本。来源不足的外部论断保留为待证据核对，不生成虚构引用。

草稿中只允许明确的缺口对象，不能将“TBD”“不适用”或模板示例写成已确认事实。结构未知但非关键的章节保留待判定状态；关键适用性矛盾仍需明确处理。

### P2：自由稿保存与核对拆分

manuscript_documents.edit 不再依据 fact_or_uncertain 拒绝保存用户工作稿。新稿件端点使用显式、最小允许字段；不盲目对 arbitrary dict 做 update。

保存路径执行身份、版本、结构等技术校验，形成持久版本、事件和幂等回执。科学分析失败不能导致输入丢失。把核对任务写入现有 outbox/任务结构，后续按保存的文档版本和研究版本运行。

保存状态（已保存/有更新）与核对状态（等待/不一致/失败）分开显示。结果只应用到对应快照；不能用旧分析将新文档标成已核对。

当前 reclassify_edit 不再用作保存许可判定。修复 text/value、数字边界、否定和上下文误判；其确定性结果作为线索，结合结构化diff和AI语义核对，不能承诺靠正则证明任意语句等价。

### P3：GenOffice 接入

在 frontend/src/features/medical-writing/protocol-workbench/office/ 添加嵌入和适配模块；ManuscriptWorkspace 保留任务准备/进度/历史，正文区域挂载一份完整文档的一实例一iframe运行时。SDK与renderer不重新实现研究工作流。

现有 protocolWorkspaceApi.mjs 的 JSON request 不能直接解析 DOCX。新增二进制读取/上传分支和同一错误合同。复用 SQLite、LocalArtifactStore、事件/CAS/恢复能力。

建议稿件保存模型：Office文档不可变快照先成功持久化，并与文档版本、研究版本和映射状态原子登记；语义投影/分析随后绑定同一快照。投影不完整时保存原DOCX并标注待核对，不将不能解析的对象删掉。数据库不得另存第二份可独立编辑的正文作为竞争主版本。

先证实原生中英文、完整表格、页眉页脚、分节、目录、链接、修订的实际打开/编辑/保存。不使用截图、简化Tiptap或HTML重新生成整稿冒充Office接入。

### P4：摘要、SOA和自然语言编辑

保留 AI 推荐/生成与确定性布局的分工。AI 产生结构化候选内容，渲染器生成原生可编辑段落、表格和字段。人工直接编辑后的内容成为当前稿，不再每次导出重投影。

将 synopsis_projection.py/soa_matrix.py 相关能力移到初次生成、显式刷新/一致性分析边界，保留有用实现而非整文件删除。

提供 replace_object 与 patch_object 两种范围明确的操作。用户明确要求替换某一表格时，可在已授权范围内直接应用并保留差异/撤销；无需对同一局部意图强制第二次确认。只有改变关键设计或扩大到未授权范围时进入对应核对。

所有 AI 操作绑定目标锚点、基础docx/语义版本、预期内容、操作ID。准备候选期间用户编辑目标时重算或冲突提示，不强写。跨文档、跨章节同步不默认发生；不得把“只改流程表”解释成全文重写。

### P5：导出与恢复

修复章节首块为table即插入“不适用”的错误。导出字节对应用户看到的指定工作版本；无模型调用、无静默术语替换、无工程词命中后整段删除、无使用当前设计重写旧稿摘要/表格。

内容清理和结构修复作为可见候选操作；合法签名空白不是必须填造的数据。初始公司模板配置与研究事实必须分开。

完成错误恢复API、历史入口、草稿持久化、哈希一致性、并发和未确认结果对账。第一版原生文献插入等功能不能被省略；外部Word改稿回导和具体第三方文献管理器互操作不擅自声称已验收。

## 3. 建议新增的最小业务接口（名称待与项目接口惯例对齐）

```text
GET  .../draft-readiness
POST .../office-draft/prepare
GET  .../office-draft/revisions/{revision}/content
POST .../office-draft/commits
POST .../office-draft/commits/recover
GET  .../office-draft/revisions/{revision}/reconciliation
POST .../office-draft/reconciliations/{id}/resolve
POST .../office-draft/objects/{id}/ai-revisions
GET  .../office-draft/revisions/{revision}/export/docx
```

这些不是已存在的 API，也不要求机械照搬一套新服务；优先在现有路由、应用服务和持久化能力内扩展。文档提交回执至少区分 document_revision、document_sha256、study_base_revision/hash、operation_id、persisted和reconciliation_status。

## 4. 报告格式

每一阶段输出 SOURCE_HEAD、CHANGESET、REQUIREMENTS_COVERED、TEST_COMMANDS_AND_EXIT_CODES、PASSED、FAILED、NOT_RUN、KNOWN_LIMITATIONS。区分单元测试、真实HTTP、浏览器、模型和Word验收。

本包没有上游可运行补丁，不得将参考设计写成“已经接入”。禁止为演示把模拟响应接入正式环境。分工建议：一名集成负责人控制文档合同和保存，入口/AI对象/SDK/独立QA围绕冻结接口并行，避免多人同时改核心状态。
