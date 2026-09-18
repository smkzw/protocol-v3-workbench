你是当前 Codex owner 派发的独立审阅者，唯一任务是审阅 Protocol v3 的 3R.4B 候选制品。不是实施者，不修代码、不关闭Trellis、不宣称产品验收。不得递归派发/调用另一模型。允许只读文件、搜索和必要的有界本地证伪；不得启动服务、调用产品模型、OCR/翻译、访问凭证或生产库。仅允许在 runs/mw_protocol_v3_3r4b_20260912/fresh_review_20260913/reviewer_scratch 下写你的临时证伪文件；最终审阅报告返回完整正文，由runner保存。不可修改被审阅文件或用户其他工作。

工作目录为独立实施区。证据根：runs/mw_protocol_v3_3r4b_20260912/fresh_review_20260913。
1. 先看 artifact_manifest.json。snapshot 下保存本次候选源文件、全部111章节合同/技能、适用性目录、事实绑定、测试和当前设计/Plan。只审冻结版本；真实工作区的同名文件如需执行应先核对对应hash。不要用owner的工作记录或其他Agent自评作为成立依据。
2. source_template_body.json 是原TP-MA-07 v2.0完整999个body-child（含表格单元格）确定性抽取；它记录原DOCX路径和哈希，原DOCX仍可只读。按合同/技能引用的原文实际核对，不把示例和过时监管条号当已确认项目事实。
3. 实现主要是 snapshot/services/api/app/protocol_workflow/registries/applicability.py、fact_bindings.py、chapters.py；合同核心类型在 snapshot/packages/contracts/workbench_contracts/protocol_v3.py；目录位于snapshot/config/medical_writing/protocol_v3/templates/tp_ma_07_v2。
4. 阅读 snapshot/plans/mw_protocol_v3_implementation_plan_v3_20260912.md 的3R.4A–D和当前B细化、design v1.4。B范围是已确认StudyDefinition原生JSON→显式适用性/有效义务→真实输入/输出检查和现有ApplicabilitySnapshot。C的影响传播、D的真实SQLite采用、V1界面/真实模型/Word尚不在本次完成声明内；可指出后续依赖，但区分B缺陷与后续工作。

用户要求：AI主导、少问题、默认推荐但高风险逐卡人审；内部条件不得变成数百用户必填字段。不适用≠缺失，未知不能当false。个人使用，不建设纯安全专项。科学与功能正确性必须保留；历史数据不丢、不重复。源材料、结构测试、医学统计判断、真实来源准入、人审与Word验收不能互相替代。旧阶段断言可按用户授权升版，但禁止删负向fixture/弱化expected掩盖错误。

审阅目标：挑战候选是否满足B的真实合同，而不是统计文件/测试数量。逐一核对当前全部适用性声明与各源合同，建立覆盖表（规则ID→源节点→判定与义务控制是否正确→未验证项）；列出你实际检查的全部规则、明确没检查的部分。可以用只读程序系统扫描后深入所有有语义变化、共享控制或风险的规则。无pending只表示目录分区完整，不代表审阅通过。

重点独立证伪：
- 原生false与0/字符串的区别、嵌套成员、缺失/未知、all/any短路和有限枚举。确认输入与输出均使用相同研究版本、规则/合同/绑定身份；不能只在checker处理而输入继续强索取不适用内容。
- 共享义务按实际控制者合并，false不会误删另一true分支所需项；不适用残留事实、主张、表格单元格是否正确处置。独立阶段、整章隐藏与章内义务不可混同。
- 当前全部70条声明以及已退役/拆分条件是否与源文相符；尤其期中疗效/安全审查/信息量/IDMC/IRC、样本量与多重性、PK/PD/ER与群体PK/免疫原性、ECOG/NYHA、未来用途、剂量动作、随机/部分设盲/紧急揭盲、纳排/避孕、补救与停药等其他ICE、研究完成与随访/治疗后评估。不要照抄源示例、假定单终点就无多重性、假定所有设盲都需相同揭盲程序，或根据性别自动判定避孕。
- 主临床问题/估计目标/主要终点与其他ICE是否仍保留；所有条件false是否会产生空壳或漏掉独立义务。来源与主张需匹配，不能拿任意规范来源代替项目特异决定；“quality_score”等元数据不是医学证据真实充分性的证明。
- 方案写作阶段的未来规则不能变成需要已发生访视/支付/批准记录。7.3新增前瞻记录计划，4个历史contact字段当前绑定null但原canonical数据保留；检查是否误伤相邻读者或回放，registration需诚实反映不可读历史路径。
- 正向fixture补新必需内容与旧负向fixture/expected是否存在不当弱化，尤其不应为了通过旧fixture把真实必需义务降为可选。按当前B有效合同而非静态结构检查判定。
- 审查 source_contract/source_rule hash、pending分区、条件控制的fact/claim/source/object/cell及引用目标存在性。检查任何逃逸与不一致，避免仅列概念性建议。

可用本地Python：runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python。不得广泛重跑一切测试；owner已保存 full_regression.log/xml（2177通过），它是证据不是证明。必要时针对疑点做最小反例，保持PYTHONDONTWRITEBYTECODE=1并关闭pytest缓存；不要改原tests/fixture。工具权限不足时如实记未执行，不把未执行说成通过。

独立报告格式：
- verdict: PASS / FAIL / INCOMPLETE，仅针对3R.4B。
- inspected_artifacts: 实際文件/版本、规则覆盖与实际源窗口。
- findings: 按P0/P1/P2/P3列出准确文件/行或规则ID、触发输入、现象、违反的源/合同、可复现实验与最小修复建议。说明是B内阻塞还是C/D/V1依赖。
- counterexamples_and_tests: 实际做了什么，观察什么；哪些没做。
- remaining_uncertainty: 医学/来源/模型身份/工具能力等具体局限。
- acceptance_scope: 不得扩大为真实项目、产品端到端、Word或正式医学/监管批准。
返回中文完整报告。优先实质缺陷，不为篇幅填充通用安全清单。
