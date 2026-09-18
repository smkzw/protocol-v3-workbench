# 3R.5A R03源与验收设计预检

状态：只读源审阅与设计准备，尚未实现criteria registry，不是3R.5A验收。D执行期间不修改其源文件/测试。依据Plan v3、继承v2 Task3R.5指定的R03修订版，选择authority_amendment中的qc_or_sop_reference条目，不回退旧路径原版。

## 已核实的源

R03修订版：`/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx`，实测SHA256 `5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9` 与当前清单一致。以zip/XML只读抽取，未启动Word或修改SOP。17表/104物理行=4身份信息行+32重复表头行+68源内容行。完整原文/段落、表格合并标记与零基定位保存在 `runs/mw_protocol_v3_3r5a_source_audit_20260913/r03_source_rows.json`；分母证据source_denominator.json。

另有一个不能丢的表头内容：T5/R0/C1在“描述/文本”之后含“试验参与者识别和招募方法。”。它不属于68正文行，必须单独保留为source fragment，不能过滤所有表头就丢失义务，也不能偷偷把既定68改成69。

## 会直接影响产品的源缺陷

1. 原E6编号不等于稳定criterion ID：有空编号连续行、6.4.0、源标题“试验目的和目的”、6.5.2“暴露标准”、6.16乱码参考提示。保留source_label/raw_text与源定位，不改外部原件。规范化名称和规范对照单列，不把这些字面错误直接写入方案正文或条件规则。
2. 一源行含多项检查：如6.3.2的estimand构成/终点/分析一致性，6.5.3的停药/退出/研究者终止及数据/随访/替换，6.13的数据来源/原始记录/系统与保存。必须逐项形成atomic obligations；68只是源覆盖分母，不是最终原子检查总数。
3. 是否出现文字不能证明医学正确。主要终点/样本量/ICE/人群/剂量和停止标准必须同时检查事实一致性、证据定位及相应人工确认；不能把“非空/含关键词”判成科学通过。
4. 源混合药物/器械、IIT多中心、委员会、安慰剂/假手术、期中分析、单独协议等条件。使用当前研究事实判适用/不适用/未决；不能对标准Ⅱ/Ⅲ期药物研究强索器械移除、IIT规则或不存在的委员会章程。保留不适用原因和source覆盖，不删除源行。
5. “排斥反应怎么办”缺少清楚适用语境，不能替它猜成妊娠/过敏等另一医学概念。原文保留、标source ambiguity，具体研究语境下由语义审阅判断；不将此词设为所有方案必须出现的自动门槛。6.16为参考提示，先标reference_hint/source_noise，不硬造方案正文义务。
6. R03的是/否列不能容纳未决/不适用/需人工评估；产品用丰富状态，导出QC回执须保留映射和必要附注，不把不适用一律填“否”。正式签署区保留空白控件，不能生成签名或已审批事实。

## 官方对照的有限用途

此次直接核对[ICH E6(R3)正式文本](https://database.ich.org/sites/default/files/ICH_E6(R3)_Step4_FinalGuideline_2025_0106.pdf) Appendix B：B.5.2明确排除标准，B.4.4覆盖试验药品/剂量/剂型/包装/标签，B.6单列停止干预与退出，B.10覆盖统计考虑，B.12覆盖质量管理。上述对照用于规范化与定位；R03的6.x保留为公司源标签，不假称R3新条款号，也不推断国内实施日期或具体项目已满足法规。

## 最小实施合同（待D及3R4验收后实施）

- extractor固定源hash并保留68条source rows、4身份字段、表头嵌入fragment及签署位置；源ID由source版本+XML定位稳定生成，E6 label仅作引用。不得因空label、合并单元格或错误拼写丢行。
- registry中一条源行可对应多条atomic obligation；每atom保存source row/paragraph、规范化检查、适用条件、semantic_node_ids、检查类别deterministic/agent4/human、证据定位规则、是否仅声明未来安排、缺少材料时状态。数目由显式拆分输出，不猜总数。
- deterministic只判能确定的结构/类型/引用解析/跨章同事实/已确认版本、数字复算等；agent4负责内容充分性和科学解释；human只覆盖必要专业取舍/真实性/最终签署，复用八类推荐卡确认，不增加68个逐条点击。
- 对SAP、委员会章程、审批、联系人与机构资质，区分“方案规定将如何做”与“已经完成/批准”的证据。AI不得把未来安排写成已经批准，缺少实际人员/中心/供应商信息时不给假姓名。
- 首批路径检查：题目/编号/版本/日期一致、内部交叉引用和外部文献可定位、缩略语实际集合、目的-终点-estimand-分析集-样本量链、干预/SOA/安全处理在同一事实版本；其他atom明确pending实施，不能因为有registry就全部标通过。
- 真实反例须覆盖：缺E6label但有文本、表头内义务、复杂一行多atom、器械/IIT不适用、未知委员会不当false、source typo不污染正文、无源审批不得填已批准、合法签署空白不误判正文占位。
- 原生Word引用/样式对照仍是独立实际制品工作，未做则不宣称通过。R03生成回执与Word标准方案不能凭XML抽取或绿色测试当作原生排版验收。

下一步：读取当前Word style/bookmark映射与TP-MA-07 node_tree抽取结果，列出真正的字段/书签/跨表引用契约；在D worker退出且整体3R4验收后，按本合同实现R03最小registry和真实路径检查。

## Word源对象与PoC复用边界补充

清洁模板SHA256仍为018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756。只读OOXML检查：正文288字段/314书签，页脚2字段/1书签，页眉1书签；合计290字段/316书签。因此node_tree的正文314与producer全story316不构成数据丢失。当前111合同引用的13种style ID、172个bookmark name全部存在；只有一项required_cross_reference声明，不能用该声明数证明全文引用已覆盖。完整源对象与对账见同run的word_source_objects.json、word_contract_source_alignment.json。

确认的功能缺口：pocs/protocol_v3/word_receipt/producers/base.py的select_bookmark_checks取前后交集并最多32项，丢失书签不会列为失败；select_cross_reference_checks跳过缺目标/空结果/error后也最多32项。applescript_bridge.py只要求这两类结果非空。word_selector_counterexample.json直接调用原函数，保留一正常引用及一丢失目标引用，结果只返回正常项目，证实不能把该抽样当作全书正确性证明。此反例不代表已实际运行Word或证明整份receipt validator一定放行；PoC另有域更新/页面证据条件仍需满足。

修订方案：复用已有Word自动化和OOXML检查，在产品adapter上绑定实际生成文档的应有对象清单，逐项返回成功/缺失/错误；业务bookmark由稳定semantic node/table身份生成，自动_Toc仅作目录域派生对象，不能要求刷新后每个历史自动名永远不变。目标语义及引用显示内容需要与输出对象一致，不只检查非空；合法无引用实例不能被强制添加无意义引用。覆盖页眉页脚、正文、脚注等实际存在story，缺失目标和本地化错误要保留失败证据。具体实现和反例测试在V1.5，不修改历史PoC验收来伪装当前产品完成。

只读应用bundle显示已安装Word16.112.4（build16.112.26090911），旧P0测试版本16.111.3；这不是运行中Word版本证明。当前producer实现hash9e214a167b7f0bf67e417e0c75e4b71b8a6c9b98cf5b5e3b5f81aba7f90fc12b。后续针对当前制品复验实际Word能力、保存结果和页面，不重跑全部历史失败、不改系统更新设置。此次未启动Word、服务或产品模型，也未修改任何SOP。

## 后续可直接接用的源映射候选

r03_candidate_node_crosswalk.json已逐行保留68条原文/位置，并给出显式候选semantic nodes；另列招募表头fragment。所有ID已与当前node_tree核对，不代表全部原子检查已实现或医学通过。特别标注estimand群体汇总量实际由3.1.2.4承载、委员会与事件随访须分拆、器械/IIT条件限制、SAP未来审批与已完成事实区分。3R.5A实施应以原文再次拆分及独立复核，不能把候选映射直接当通过的registry。

## 相邻3R.7A占位检查复用前的实际反例

只读导入现有medical_writing_content_quality.py并直接运行实际_scan_text（合成document/section对象，非模型/服务）：合法“未提供书面知情同意者不进入筛选。”与前瞻程序“数据将在生物统计人员确认后锁定。”均被unresolved_draft_marker判approval_blocking=True；真正草稿“样本量待医学经理确认后写入。”也命中。完整源hash、匹配片段和结果见legacy_placeholder_counterexamples.json。此证据证明旧detector函数的误报，未冒称整个v3 UI已有该调用。

3R.7A/最终正文检查需保留真实草稿正例并补合法否定、未来流程、引用原文、签署控件反例；先按内容角色/完整句意区分，不能把任意“未提供/生物统计确认”都设为硬缺失，亦不能删除整个占位规则凑通过。只有文字疑点而无确定草稿含义时交给内容审阅，不让用户为合法文字反复改写。旧链触达时最小接线修复，未触达的旧页面不先广泛改造。当前独立A-D审阅源码不变，本轮尚未实施此修复。


实现复用定位：registries/chapters.py的CheckerFinding(code/severity/location/message)与FixtureCheckResult.deferred_qc_obligations已经区分确定性结果和未执行医学判断；packages/contracts/workbench_contracts/protocol_v3.py的PositiveQcRule仅是规则文本，不能当作已执行QC回执。3R5A注册表先显式标实现与未实施，7R按正式typed finding接线；不再创建平行状态库，复用已有事件/制品版本。
