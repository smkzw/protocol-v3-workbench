# 下一阶段实施明细（待本阶段会商裁定后并入Plan）

| 工作项 | 现有入口/主改文件 | 交付行为 | 完整构建后验证 |
|---|---|---|---|
| 确认依赖双绑定 | canonical/decision_inputs.py；application/commands.py、service.py；registries/dependency_graph.py；agent2/study_input.py；api/design.py | 生产读集原样保留；医学确认独立持久范围；其他卡合理确认不循环重开剂量；未知依赖不默认为无关 | 八卡不同确认顺序、相关/无关事实变更、旧事件回放、同key不同范围冲突、科学依赖解释 |
| 七类剩余建议 | agent2/clinical_worker.py、recommendations.py、option_bundle.py；api/design.py；前端RegimenDesignWorkspace相邻共享卡 | 模型结构化建议/备选/证据/理由预填，逐卡人审写入同一StudyDefinition；不新增数百必填表单 | 实际Ⅱ/Ⅲ资料、优效/非劣、期中/无期中、estimand/ICE与分析集一致；≤20点击中包含所有实际确认 |
| 整稿恢复与版本 | agent3/manuscript_request.py、manuscript_coordinator.py；application/manuscript_documents.py；api/manuscript_drafts.py；ManuscriptWorkspace.jsx | 旧请求可恢复、新study明确新稿；全章状态准确；保存一次完整版本；旧回执不回退新正文 | restart、并发恢复、断网失回执、配置漂移、源文件不可用但原包完成、保存中断、后继版本 |
| 受控编辑 | canonical/document.py既有EditClass/reducer；application文档层；api正文端点；ManuscriptWorkspace及受控编辑组件 | 正文/表格均全屏；输入法不误提交；同能力格式可保存/重载/导出；参数变化经研究事实修订，不以客户端wording标记绕过 | 中文IME、切章/切项目、撤销/未存恢复、版本冲突、表格合并/附注与Word保持、事实修改提示与采纳 |
| 医学与R03 QC | qc/r03.py；config/.../qc/r03_criteria.json；既有source/claim/medical-admission contracts | 每项有输入/来源/判定/可修复建议；同项目事实跨章一致；工作稿不伪造准入 | 主要终点/estimand/样本量/人群/给药/SOA/AE报告一致性、数值复算、缺证据不冒PASS |
| Word与文献 | 复用现有文档导出链，接SemanticDocument与word_source_objects.json；选定准确现有producer后最小接入 | 整稿有序、模板样式、原生目录页码/域/交叉引用/横向SOA/跨页表头；正常签署空白合法；统一引用实体 | 原生Word保存后DOCX/PDF实渲染，输入到最终artifact绑定、书签/域全集核对、版本下载一致性 |
| 最后完整用户验收 | ego(lite)唯一TaskSpace；既有后端/前端测试目录；原生Word | 建项→AI推荐→确认→全部章节→编辑保存→导出；Desktop优先 | 真实项目独立选用须用户授权，合成工程与真实医学验收分开；16/14字号目标、风险红tag、错误恢复、点击/自由文本计数 |

以上主路径均相对本隔离区。不得写live/医学监查/外部SOP；不能用本表授权真实cutover。执行时完整读取相关定义，Files若需扩展先记录实际原因。用户暂停优先：尚未执行任何下一阶段工作项。
