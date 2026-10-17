# 目标架构

## 技术栈不换
React 前端、FastAPI、SQLite、GenOffice/Office 快照、现有 durable job。不新建服务、数据库、事件平台。

## 主数据对象（尽量复用现有类型，只补必要字段）
| 对象 | 内容 | 复用自 |
|---|---|---|
| ProjectProfile | 药物名、靶点、分子类型、给药途径、适应症（含标准化术语）、分期、可选资料 | authoring_journey / product_profile |
| CompetitorSet | 检索到的竞品研究、方案文件、分类标签、优先级分、用户确认的前 K 个 | writing_reference + CT.gov ProvidedDocs 下载链 |
| StyleKit | 按模板语义节点对齐的竞品段落范例、术语表、句式、各节篇幅分布 | 新建（数据，不是代码） |
| ClauseBank | 惯例类条款（AE/SAE、揭盲、妊娠、伦理、数据管理、质量……）的共识写法 + 出处 + 法规锚点 + 可变参数 | 取代 medical_writing_repository.py 的硬编码骨架 |
| StudyDefinition | 用户确认的结构化研究事实（唯一事实源） | 现有 typed StudyDefinition |
| DecisionCard | 一个设计决定：选项、各选项分析、推荐、依据、影响的章节 | authoring_journey 推荐卡 |
| SectionCard | 每个模板语义节点的写作卡（目的、必含要素、消费的事实、风险等级、篇幅范围） | 由 111 份冻结章节合同**压缩生成** |
| SectionDraft | 正文 + 逐句依据 + 不确定标记 + 检查器结果 | full_draft section candidate |
| Manuscript | 当前 DOCX（唯一当前稿） | manuscript_documents + Office snapshots |

## 生成流水线
```
ProjectProfile ─┬─> 竞品检索/下载/解析/分类/排序 ─> 用户确认 TopK ─> StyleKit + ClauseBank
                └─> 文献检索(PubMed) ─> EvidenceSpans
StudyDefinition <── DecisionCards(AI 选项+分析+推荐, 用户选择) <── StyleKit/竞品设计统计
SectionCard × (StudyDefinition 相关子集 + StyleKit 范例 + ClauseBank 条款 + EvidenceSpans)
   ─> 写作模型逐节生成(结构化输出)
   ─> 检查器(确定性 + 异族模型) ─> 标记/定点重写(≤2次)
   ─> 确定性渲染器（样本量、剂量表、SoA 表、分析集等数字与表格）
   ─> Manuscript(DOCX) ─> Office 编辑/核对/引文/导出
```

## 单一所有权
- 研究事实只在 StudyDefinition；正文里的数字由渲染器从 StudyDefinition 生成，模型不产出关键数字。
- 当前稿只有 Manuscript 一处；legacy working_copy 只读，提供一次性迁入，不再双写。
- 定稿采用**文档级发布 + 缺口清单**，取消 107 章逐章冻结。

## 保留
StudyDefinition、durable job 与恢复、Office 快照/回执校验、ADDIN 引文、CT.gov 下载、PubMed 外查、TP-MA-07 v2 节点树与语义 ID、DOCX 导出（目录域/页码/横向 SoA/表头重复）、模型生命周期编排器（如继续用本地模型）。

## 删除或冻结
| 对象 | 处理 | 原因 |
|---|---|---|
| `medical_writing_repository.py` 标题关键词骨架（`_SAFETY_REGULATORY_HEADING_MARKERS` 及各 `_SAFETY_*_TEMPLATE`、外用→PK不适用） | 删除，迁到 ClauseBank | 按标题判医学规则、写死实施细节、个案补丁 |
| `medical_writing_full_draft.py` 样本量/剂量正则守卫改写正文 | 删除改写；保留为只读检查器 | 正则改模型正文、公式覆盖不全、按旧章号触发 |
| `_instruction()` 5千字补丁提示 | 用分层提示替换 | 规则冲突、适应症专属条款 |
| `medical_writing_competitor_triage.py` 心衰/COPD/UC/CRSwNP 专用函数（约24个） | 用通用术语标准化 + 语义匹配 + 用户确认替换 | 针对测试项目拟合 |
| `medical_writing_corpus_policy.py` 写死公司文件名与权重 | 移到运行时数据配置（不入库） | 数据进了代码、且是公司资料 |
| 107 章逐章冻结流程 | 改为文档级发布 | 正式 Word 不可达 |
| 多模型会商 / 多测试者无上限 LOOP / dwfrun 工作流 | 停用 | 见 06_AGENT_METHOD |
| `runs/` 4.9G 入库 | 移出 git，.gitignore | 仓库公开且臃肿 |
