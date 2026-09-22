# WP1 双入口交接与带缺口正文
**依赖WP0；构建期间只做源码/diff核查。**

文件范围：App.jsx、SynopsisProjectIntake、AuthoringJourneySetup、AuthoringCandidatePackagePanel、ProtocolIntakeWorkspace、ManuscriptWorkspace；main.py、medical_writing_full_draft.py、ai_gateway.py、ai_task_runner.py；现有contracts与protocol_workflow的research intake/manuscript接收服务。只在真实消费者所需处扩展。

步骤：
1. 明确经摘要导入或从零推荐得到的研究定义、来源和确认记录的交接payload；建项成功不可只切project丢成果。兼容已有项目，不能把缺乏确认记录的值自动升格。
2. 新章节合同允许支持正文＋缺口/决定共存。缺口包含稳定身份、目标位置、类别、最小行动及来源；四类至少区分资料确缺/决定未定/存在未检索/映射失败。
3. 升版prompt/gateway/normalize/artifact/UI合同，旧v9只读。取消source_gap/decision_required必定清空全章的机制；无支持正文仍诚实为空，不凑80字通用说明。
4. full_draft的输入和接收两端均须适配：descriptor从选定主路径取得研究绑定、模板节点、来源及目标范围；旧repo仅兼容输入，不为新项目创建可写旧正文。将full_draft作为候选生产者适配到现有manuscript接收服务；映射语义节点、段落/表格、引用、缺口及研究绑定。不要先写旧working_copy再双库同步。
5. UI主动作“打开工作稿”；可定位缺口旁给简短行动，关键科学未决显示需确认，不使整个编辑器不可用。已有人工Office保留当前，新候选明确选择后接收。
6. 对真实模板建立“适用目标/有正文/有表/真实缺口/不适用及依据”覆盖清单。85目标不等于整本完整；概要/SOA/流程图/参考文献/附录需实际内容或明确待办。

实现完成证据：路径/字段/调用链差异与保留的历史兼容说明。不会因为adoption_ready=true就宣告完整。

WP6验收：A01–A06/A13–14/A19/A23，B01/B02/B12；同章有两段支持正文＋联系人缺口能编辑/保存/下载，关键未定不被写成既定要求；两个入口不用重复上传/抄录。
