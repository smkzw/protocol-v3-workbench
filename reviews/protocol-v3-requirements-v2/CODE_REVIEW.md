# 第二轮定向审阅与变更裁决

基线：dd2018e0aa7da0176066cedccdf2075f9ec57eb4。本轮关注用户已明确的需求与稿件主链，并非重新逐行审计全仓库。所有问题需在修复前添加最小回归测试。P0/P1/P2为建议修复优先级，非已发生损失的证明。

## 1. 需求冲突：现在已有明确方向

| ID | 优先级 | 实际位置/行为 | 结论及最小改造 |
|---|---|---|---|
| R-C01 | P0 | agent3/chapter_facts.py：生产残余推荐中有具体样本量假设、鼻科排除标准、制剂保存条件；MODIFICATION_WATCH 可推动修改现值 | 用户已判定不符合要求；从通用路径移除，重做来源/项目驱动建议；旧记录先溯源而非删除 |
| R-C02 | P1 | manuscript_plan.py、manuscript_request.py、ManuscriptWorkspace.jsx：所有适用章节facts_ready/not_applicable才能起草 | 改成关键设计准入与非关键缺口；不是关闭全部检查 |
| R-C03 | P1 | application/manuscript_documents.py：任一fact_or_uncertain使整个修改批次返回document=None | 与自由稿冲突；先持久化工作版本，再按该快照显式核对 |
| R-C04 | P1 | agent3/word_export_production.py：导出重新投影摘要、替换SOA、术语替换、按标记删除整段 | 删除这些行为在最终导出路径中的职责；可复用为初次生成或可见修改候选 |
| R-C05 | P1 | ManuscriptWorkspace.jsx：残余建议只显示前六项basis却提交所有路径 | 不能作为关键决策确认方式；非关键缺口无需一键确认假定事实才能开始写作 |
| R-C06 | P1 | 旧规格无缺口/禁止浏览器Word、旧测试事实修改必须拒绝保存 | 以版本化需求修订替代；保持事实不自动确认与技术原子性测试 |

R-C01/R-C05及旧文件细节继承上一轮同一固定提交的读取结果；本轮重验main未变化。本轮直接重读R-C02/R-C03/R-C04相关实现。

## 2. 可从源码确定的功能缺陷/明显缺口

### B01：章节首块为表格就被写成“不适用”【P1，静态确认】

word_export_production.py 在切换 node 时执行 `if block.get('block_kind') != 'paragraph': add_paragraph('本节不适用于本研究。')`。因此合法的表格首块同样触发无依据的不适用文本。

修复依据：真实章节适用性状态，而非块类型。回归：一个明确适用、以表格起始的章节不得出现这句；真正不适用章节按用户选择和模板显示。

### B02：表格内容读取字段不一致【P1，接口对照】

application/manuscript_edits.py 的 block_content_text 读取 cell.value；当前 ChapterDraftPreview 与结构化稿使用 cell.text。合法text表格可能被提取为空，变化被误判为format_only。新需求下其影响改为漏报核对，而非仅是错误放行/拒绝。

修复需按schema版本识别结构并取完整文字/数字/脚注，而不是把所有schema强制设成value或静默读空。测试合并单元格、text和明确支持的历史schema；未知schema返回不完整诊断。

### B03：字符串包含不能证明研究意义未变【P1，确定性逻辑可分析】

reclassify_edit 检查旧fact字符串是否从新稿消失，100仍包含在1000中；否定句可保留相同关键词；纯新增内容在claimed_class=wording_only时仍返回wording_only。

修复应保留可解释的数字/单位/否定信号，并用有版本的语义核对补充；不再以它阻止稿件保存，不声称少量正则保证全面医学等价。

### B04：段落编辑回执的块hash/时间不同步【P1，静态确认；下游影响待测】

manuscript_documents.edit 更新new_block后构造revision，但未按新content重算各块content_sha256；计算now后未显式更新document.updated_at。旧模型仅验证hash形状不保证与内容一致。

仅允许服务端负责的派生哈希与时间字段；基于新内容计算，测试正文、表格、空操作、幂等重放与旧事件兼容。

### B05：前端恢复调用没有对应接线【P1，上一轮接口对照】

ManuscriptWorkspace 使用 `recoverEdit?.`；当前protocolWorkspaceApi没有该方法，manuscript_drafts路由没有独立edits/recover。后端已有recover_edit方法不等于页面重载后的完整恢复。optional chaining会掩盖接口缺失。

补齐同operation_id、同payload重放/查询；未知结果先核对，不为重试生成全新操作覆盖新版。

### B06：历史入口不可达【P2，上一轮静态确认】

HistoryVersions以open=false初始化，entries仅open时计算，而打开按钮仅entries.length>0才显示。没有初始可点入口。

按钮根据历史存在性显示或始终显示折叠入口；打开后加载。不可通过删除历史规避。

### B07：草稿不是按键级可靠暂存【P1，上一轮组件对照】

ChapterDraftPreview的ParagraphEditor输入只在内部state；父级stashDraft主要在提交成功/失败执行。刷新或切换前未提交文字的恢复不能仅靠已有localStorage说明宣称已实现。

建立版本绑定的编辑缓冲和持久化队列；真实IME测试与刷新恢复，遇到分析错误仍保存输入。

### B08：恢复响应哈希命名不一致【P1，上一轮静态候选】

首次saved恢复组装documentSha256，而其他编辑路径读取document_sha256及其他snake_case字段。需真实走该分支验证422/恢复失败，不只靠模拟receipt覆盖。

统一客户端边界一次normalize，严格断言缺失字段；不得用空hash继续提交。

### B09：章节事实派生进度实例未按研究隔离【P1，上一轮实例范围确认；并发后果待测】

composition挂载一个ChapterFactsDeriver，其progress由不同project/study的路由读取。需要查明串进度、并发互斥及重启恢复范围。迁回现有持久任务/按study和run隔离，不另写第二套job引擎。

## 3. 新一轮发现的提示词审阅项（不是已证实的生成结果）

chapter_draft.py 的行文基准固定了具体时间窗示例、术语偏好和摘要内容形态。它们有可能是风格策略，也有可能继承了某个案例的特殊要求。

必须区分：可配置风格模板；当前研究数值；明确标为非默认值的示例。不能因为提示词出现数字就报告实际生成已被污染，也不能允许示例成为缺失参数的默认答案。用对照输入检查输出是否随研究变化。

## 4. 应增加、退出主路径和暂不删除的内容

### 建议增加的最小能力

统一入口模式/来源预填映射；关键设计准备度；草稿缺口对象；Office工作版本与映射状态；按快照核对及影响清单；范围明确的AI对象编辑；当前版本无内容重写导出；恢复与反拟合回归。

### 退出生产主路径的行为

无适用性约束的案例事实；为了填满合同强写predicate.expected；草稿事实编辑阻断；自动导出重写摘要/SOA；导出关键词命中后整段删除；未展示内容的批量关键确认；用旧全文生成结果覆盖用户稿。

### 不能直接删除

StudyDefinition、来源原文/版本、证据、CAS、事件/回执、任务恢复、历史记录、真正不适用判断、通用表格构建、旧导入解析及仍被其他子系统使用的Tiptap依赖。

新增模块能否复用现有实现必须经调用图和测试证明；不以“文件很大”为删除依据。

## 5. 固定提交源码入口

- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/agent3/manuscript_plan.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/agent3/manuscript_request.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/agent3/chapter_draft.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/application/manuscript_documents.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/application/manuscript_edits.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/services/api/app/protocol_workflow/agent3/word_export_production.py
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/frontend/src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.jsx
- https://github.com/smkzw/protocol-v3-workbench/blob/dd2018e0aa7da0176066cedccdf2075f9ec57eb4/frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs

状态：静态审阅与合同对照；本轮未运行整库或Word测试。修复是否通过必须由Agent提供实际回归证据。
