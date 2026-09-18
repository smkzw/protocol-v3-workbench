Active task: .trellis/tasks/09-13-protocol-v3-3r5a
你是Codex owner派发的单一E04执行worker。实现3R.5A的R03部分，不自行接受任务，不递归派发/会商，不调用产品模型/服务/OCR/翻译/Word，不访问凭证或生产库。只写下面允许路径及自己的run目录。源码/外部SOP/历史runs/Plan/Trellis其余全部只读；不commit/reset/cleanup。

先完整读当前全局AGENTS、项目AGENTS（旧路线受当前全局/用户覆盖）、active task prd/design/implement；Plan v3 §4的3R5A，readonly v2 Task3R5及design1.3 §4六L1登记；新design1.4优先。读取reviews/mw_protocol_v3_3r5a_source_preflight_20260913.md，runs/mw_protocol_v3_3r5a_source_audit_20260913的r03_source_rows.json、source_denominator.json、r03_candidate_node_crosswalk.json、atomic_split_examples.md。这些是source准备/候选而非已接受医学registry，须核对实际源。原DOCX实际路径：/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx；SHA256 5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9。zip/XML只读，禁止改源。

允许新增：scripts/qc/protocol_v3/extract_r03_criteria.py；config/medical_writing/protocol_v3/qc/r03_criteria.json；services/api/app/protocol_workflow/qc/__init__.py和r03.py；tests/protocol_v3/test_r03_criteria_registry.py；本run runs/execution/mw_protocol_v3_3r5a_r03_20260913/**。不能修改现有A-D代码/类型/配置/其他测试/word/terminology，owner将并行其余disjoint准备；不跑全量protocol_v3（只需本任务定向，避免其他正在进行的独立工作影响）。

交付：
1 标准库确定性源提取可重复脚本+实际注册JSON。完整保留17表104物理行=4身份+32表头+68内容；另外T5/R0/C1表头招募义务单独fragment；空E6label、合并格不丢，raw source与normalization分开，源hash+XML定位稳定ID，不用6.x当唯一ID。不丢签署位置，不伪造签名。源文编号/错词/6.16乱码参考提示原样保留，不抄到新正文或当普遍内容义务。
2 每个内容行明确拆原子义务，追溯源行和短片段，normalized check、deterministic/agent4/human、candidate semantic nodes经当前node_tree验证、适用条件、证据要求、实现/未实现状态。source_noise/reference_hint显式处理并保留分母。不要把所有68行机械1:1复制成atom，复合estimand/退出/委员会与随访/数据治理/SAP要求分别可核对。适用条件复用明确规则ID或声明尚未接线；没有研究事实的未知不当false。任何条件不清不要猜医学结论（排斥反应不改写成过敏/妊娠）。同一个人工确认可覆盖相关义务，不造68张卡。
3 六项L1目录登记：版本四点一致、缩略语闭环、文献双向、文字性交叉引用、数字单位、登记一致性。最小qc/r03.py实现纯输入/输出的客观版本和内部引用检查，可用明确typed输入（真实文档投影稍后接），空材料不得伪pass；当前版本在当前位置一致，修订历史旧行合法保留。文字引用检查以明确目标对象清单为准，不只是有数字。其余未接产品/尚未实施检查诚实标pending，不硬用关键词判断科学充分性、文献时效或正式批准。实际生成模型/Word/UI消费者属于V1，不能声称已接。
4 与已有CheckerFinding/FixtureCheckResult及当前registry接口保持可复用语义，无新数据库/框架。registry loader检查源ID/绑定/重复/未知检查实现引用等真实可靠性，不搞通用安全工程。图/源计数与医学充分性分开。
5 先写真实行为反例再最小实现，至少无label、有表头义务、复合行拆分、未知/条件不适用、当前版本不同/历史旧日期允许、引用目标缺失/空材料、源错词不污染规范化、签署空白不当草稿。保留原fixtures，不xfail/降expected。定向pytest及生成物确定性/source hash验证，不能文件数即通过。

工程路由是GLM-5.3-Flash:max，与产品调用禁止不同。既有adapter实际连接已验证无需新产品probe。长任务原session硬等待，只有terminal结果后owner验收。本轮7200秒总预算，剩余未知不自动重派。报告worker_report.md含完整允许文件hash、源分母/atom分母、每类实现/未实现清单、实际红绿测试日志/命令与问题；最终完整报告返回runner。不夸大源充分性/科学/Word/UI/全产品，不更新Trellis。
