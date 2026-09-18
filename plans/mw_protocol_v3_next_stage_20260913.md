# 下一阶段详细计划（会商后修订，暂停后须用户继续才执行）

## 当前范围与完成定义
当前阶段仅整稿请求/子章持久协调、完整候选一次保存和当前版本阅读、康哲资料/推荐/阅读皮肤源码接线。所有新增源码未测试，未载入实际API；不是V1.1或整产品验收。原111载体、来源与条件成果不重做。用户要求阶段收口会商后无损暂停，不进入下一阶段。

## 下一阶段目标与顺序
1. 确认语义：保留producer原decision_input_binding，增加服务端医学依赖confirmation_binding，原事件固化范围/版本；防止八卡确认循环。未知新增键不能直接判irrelevant，同key不同绑定必须冲突；历史原回执与当前有效性分开。依赖解释和范围需独立来源核验。
2. 推荐完整性：把其余七类重要研究建议接入真实StudyDefinition；以项目资料给预选/推荐/依据/待补最少问题，高风险逐卡人审。优效不索非劣界值，无期中不索alpha，未知不能误当false。全部适用事实由资料/推荐补齐，不让用户填数百字段。
3. 整稿生命周期：原生成run/来源身份保留；研究改变时明确新稿入口，不覆盖旧稿；中断原key恢复；全部适用章节齐全才可成稿；对已保存旧初稿明确当前study绑定失效状态。将阶段会商发现的剩余缺陷先解决。
4. 受控编辑：段落、结构表格和附注编辑，IME期间不提交；本地未提交内容按项目/研究/文档版本保存，刷新/切章/保存失败可恢复。当前版本CAS、同operation回执和当前版本分开。不能通过前端自称wording_only来改已确认事实；不确定修改形成事实候选并走StudyDefinition确认路径，禁止静默改变研究参数。
5. 医学与跨章QC：同一事实支持目的/终点/estimand/ICE/统计/样本量/人群/剂量/安全报告/SOA；结构通过不代表医学通过，医学准入不编造。工作稿为PROPOSED；正式正文零占位/待确认/生成提示，合法签署控件保留。
6. Word实际导出：复用现有文档链/模板资产，不另造浏览器排版引擎；目录页码交叉引用、横向SOA、跨页表头、字体、原生Word及PDF结果逐一核对；绑定原输入和最终保存版本；eCTD仅文档就绪，不冒充正式sequence批准。
7. 完整构建后统一测试：按用户指令此前不新增/运行阶段测试。最后统一后端/SQLite/重启/并发恢复、前端IME/项目切换/失败恢复，ego(lite)完整用户路径与视觉；关键点击≤20、必填自由文本≤5、正文16辅助14目标；原生Word实渲染。失败修复后定向复验，不反复无理由跑全套。

## 执行与目标控制
用现有Trellis一套状态，不增并行看板。owner主集成，有界worker独立文件并行，重要医学语义/最终视觉按全局AGENTS独立会商。每派发/恢复/用户变更读取全局AGENTS。runner7200硬等待与原句柄分段等待，慢不重派，unknown先对账。产品既有探针/来源成功任务不重跑。目标设置先更新可读prompt文件，native goal工具无objective/pause接口，不写内部数据库、不假称goal complete/blocked。暂停后没有用户继续不启动本计划。

## 本阶段会商落实与后续验证义务

会商见runs/conference/mw_protocol_v3_stage_close_20260913/evidence_single_object.md。owner接受P1/P2根因，但不采纳版本冲突后自动新operation覆盖当前稿的建议：先保留原intent、读当前稿，只有用户明确另存才产生新版本。源码补齐新研究新稿入口、blocked提示、study绑定变化提示及原source一次显式retry；该批仍未测试，不能删除对应最终异常路径验收。确认依赖可复用canonical/legacy别名解析，不能把章节readset直接当医学确认范围。表格编辑必须共用typed codec/schema与hash计算，Word覆盖分母从已绑定完整ChapterContract派生，不用block上的contract ID冒充完整范围。

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

## 最终会商后保留的具体待办
P1-R1已通过精确内部recoveryKind源码接通，不再按未实现误排；但真实409/另存链仍须最终测试。首先补新稿按钮禁用原因、当前/历史版本选择与存储保留策略、删除无消费者重复索引前的回溯迁移方案、内部不变量错误的正确归属和措辞。不得删除历史记录来简化恢复。完成构建后重点覆盖真实client过滤、HTTP409、断网重试、planRefresh不触发模型重派、原source retry身份；不能只用绕过client的mock证明UI恢复。
