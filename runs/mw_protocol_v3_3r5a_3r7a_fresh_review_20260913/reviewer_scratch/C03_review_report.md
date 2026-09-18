# C03 独立来源/工程评审报告 — 3R.5A / 3R.7A（冻结快照 20260913）

评审人：C03（fresh GLM-5.3:max，zcode/zcode/GLM-5.3，off_peak）
评审根：runs/mw_protocol_v3_3r5a_3r7a_fresh_review_20260913（snapshot 252 文件）
日期：2026-09-13。只读评审；本 scratch 外零写入；未启动 Word/服务/模型调用；未读执行方 worker 报告。

## 结论：PASS（限于本次 ENGINEERING/SOURCE 声称范围）

未发现 P1/P2 缺陷。已声称实现范围内（R03 注册表+两个 typed 检查、Word 源对象清单、术语/占位检测三消费者接线）全部关键声明经独立复现成立。V1/V1.5 未实现边界（生成模型、原生 Word、UI 消费者、文档投影）在制品内诚实登记，未冒称完成。P3 观察项见下，无强制修复项。

## 哈希与制品一致性（非LLM锚点）

- SOP QC 表 docx：SHA256 5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9 ✓（与合同一致）
- TP-MA-07 v2.0 docx：SHA256 018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756 ✓
- artifact_manifest.json 自身 b57e816e…94 == dispatch_contract.source_manifest_sha256 ✓；快照 252/252 文件哈希逐一核对全部一致，快照无多余文件 ✓
- 当前树 252 个 manifest 文件哈希与快照全部一致（测试按合同在当前树执行的前提成立）✓
- 字节级再生成：r03_criteria.json（从冻结 docx 重提取，sha 410346cd…bed 与提交件 cmp 相同）；word_source_objects.json（sha 98338306…b81 与提交件 cmp 相同）→ 两注册表均为确定性的源驱动制品，非手工拼装 ✓

## Scope A — R03（extract_r03_criteria.py / qc/r03.py / r03_criteria.json）

- 独立提取（reviewer 自写脚本，未复用项目代码）：17 表、104 物理行、4 身份行（T1）、32 表头行（16 表×2）、68 内容行（54 有编号+14 无编号）与注册表 denominator 完全一致；104 行文本+gridSpan/vMerge 结构逐行交叉比对 0 差异（independent_rows.json vs regen_r03_criteria.json source_rows）。
- T5/R0/C1（0 基 = 物理第 6 表表头描述列）：raw_text "描述/文本“试验参与者识别和招募方法。" 原样保留（含杂引号），义务拆出独立原子 r03-t05-r00hdr-recruitment_method，不计入 68 分母、未随表头过滤丢失 ✓
- 129 原子全矩阵审阅（atoms_matrix.txt）：68 内容行全覆盖；复合行拆分可追溯（estimand 行 7 原子、退出情形行 7 原子、委员会行 5 原子、CtQ 行 7 原子、数据治理行 7 原子、SAP 行 3 原子）；类别 14 deterministic/109 agent4/6 human；状态 5 implemented/124 pending；implemented 均绑定 check_ref 且 wired_checks 与 r03.KNOWN_CHECKS 一致。
- 语义陷阱逐项核实：排斥反应原子（table[5]/row[10]）保留原词、source_ambiguity、unknown_context、未改写为过敏/妊娠等概念；ae_followup applicability=always（委员会设置不免除）；specific_event_followup conditional/not_wired、未知未决不当 false、与委员会章程规则独立；SAP 批准为将来时点安排（"已批准"不出现于 normalized）；IIT/CSR 参考提示为 reference_hint 不构成普遍正文义务；"暴露标准""试验目的和目的""Lal""DescrIDescription" 等源噪声保留于 raw、不进入 normalized（生成期+loader 双重校验）；6.4.0 等旧 6.x 标签仅作 source_label，atom_id 由定位符派生；签署段落定位 body/paragraph[22] 经独立提取核实为唯一含"填表人签字"段落，空白控件合法、不判占位、不伪造签署。
- 六项 L1 单独登记（l1_checks），仅 version_four_point 与 textual_cross_reference 标 implemented（typed_input_only），其余四项带 pending_reason；product_wiring 全部 not_wired_v1/pending — 与实际实现相符。
- qc/r03.py 两个 typed 检查：None/空材料/纯空白字段 fail-closed（含 owner 探针历史反例）；revision_history 永不参与比较（旧行合法）；subject_id 全路径保留；引用按显式目标清单解析（非"含数字"），重复/空白/未解析目标均报错；projection_completed 区分"显式评估的零引用范围"与"未投影"，且声明完成不放行脏字段/未解析目标（reviewer 探针 4/5/6 复核）。

## Scope B — Word 源对象清单（extract_word_source_objects.py / word_source_objects.json）

- 316 书签（264 _Toc 派生 + 52 源书签）、290 域（275 internal 全部 resolved、13 TOC/SEQ/PAGE/NUMPAGES 观测型、2 external）全部映射，无 32 项上限（合成 40 项反例测试）、无成功交集过滤（合成 missing/ambiguous 反例测试保留并报 finding；当前源 findings=[] 为真实状态：13 required styles 全存在（实际 styleId）、172 required bookmark 名全存在）。
- 外部文档 HYPERLINK 带本地片段 → external_document_anchor（external_not_verified），不误记为本文档内部缺失书签（测试+真实源 1 例）。
- 源 XML 多余 bookmarkEnd（document.xml 314 start/321 end，孤儿 id 18-23、121）作为 source_bookmark_end_remnants 观测保留，scope 明示 source_observation_not_generated_document_acceptance；header/footer 的 _GoBack/_Hlk89462645 无伪造 node 归属（owner=None）。
- 制品 scope=source_mapping_only_not_native_word_or_generated_document_acceptance、native_word_invoked=false、required_cross_references 仅 1 条声明（"表 1 伴发事件及处理策略"）如实反映，未夸大为全书文字引用闭合。字节级再生成一致（依赖当前树 pocs/contract.py 等快照外模块，前提为 252 文件哈希一致已验证）。

## Scope C — 术语/占位修正（terminology + 三消费者）

- library.py：TextUnit 带 role/locator；reference_title/source_quote 保留原文且强制 source_locator（缺则 quote_source_missing），但引用块旁的草稿指令仍被 iter_unresolved_draft_markers 检查（非整块豁免）；template_instruction 非空即 error；signature_control 空白合法且不豁免草稿/术语检查；"受试者"仅 warning 建议试验参与者（公司偏好、非法规禁用、不自动替换，terminology.json basis 明示）；全角％/全角单位 warning 且明示不自动换算；半角 μg、方案编号/版本/日期串不误报（探针 10）；缩略语清单基于实际使用位置，missing/unused 区分，full_form_review=not_performed；rule_status 诚实登记 dose_unit_upright=requires_word_style_check、first_definition=pending、full_form=requires_semantic_review。
- 三消费者接线：medical_writing_content_quality._scan_text、ai_task_runner._validate_protocol_full_draft_output（:2708）、medical_writing_full_draft.adopt（:696）均使用共享 iter_unresolved_draft_markers（按子句豁免合法执行条款）；旧链直接导入原始 UNRESOLVED_DRAFT_MARKER_RE 的消费路径已消除（全仓 grep 复核）。"未提供书面知情同意者不进入筛选""数据库…确认后锁定"两个合法执行句不误判，同段/同格真待确认内容仍定位（新测试 test_draft_marker_context.py 10 参数组+采用路径真实 adopt 反例）。
- 旧负向 fixture 未削弱："<0}"混合闭合符、内部传输词、待医学经理确认、未提供/尚未列入等旧 expected 全部原样通过（tests/test_medical_writing_content_quality.py 129-167）。

## 执行的测试与局限

- 命令：env -i … PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests:tests/protocol_v3/integration:tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest <8 个文件> -q -p no:cacheprovider --tb=short → 95 passed / 0 skipped / 17 warnings（FastAPI on_event 弃用告警，无关）。含真实 DOCX fixture 对照（rux/d001/my008）。
- reviewer 独立反例探针 10 组：reviewer_scratch/independent_probes.log（含 1 项保守方向过度检出，见 P3-2）。
- 未运行完整 protocol_v3 套件（按合同只选决定性测试）；未启动 Word/渲染（V1.5 边界）；R03 注册表医学充分性、逐原子适用性判定与人工确认未执行（制品自声明 registered_not_accepted，与事实相符）。
- 模型独立性受限：执行方为 Flash、本评审为 GLM-5.3，同提供商家族；以哈希核对、字节再生成、逐行独立提取、测试复跑等非 LLM 锚点补偿。

## V1 未实现范围（与缺陷区分，不构成本次扣分）

生成模型/原生 Word/UI 消费者接线、真实文档投影（含 projection_completed 的投影证明）、全书文字引用闭合、Word 字体直立/千分位/范围号 style 检查、缩略语首定义有序消费、v3 正文角色化消费者 — 均在制品内显式登记为 not_wired_v1/pending，未发现冒称。

## P1/P2/P3 发现

P1：无。P2：无。

P3（观察/过程项，无需修复即可交付）：
1. dispatch_contract.json 记录的 route_manifest_sha256（ef297ff3…）≠ 当前 scheduled_route_manifest.json 实际哈希（168dadd1…）。差异源于 07:15:57 off_peak 评估重写路由清单（内容与本次会话路由 zcode/GLM-5.3 相符）。过程性记录差异，不影响三 scope 制品。
2. 合法执行条款豁免为整子句全匹配：带限定词的合法变体（如"若受试者未提供书面知情同意书，则不进入筛选。"）仍被报 unresolved_draft_marker（independent_probes.log probe 1）。方向保守（转人工复核，不产生假通过），与代码注释声明的取舍一致；如未来放宽需保持同子句草稿指令可见性。
3. r03 引用检查的 projection_completed 为调用方声明信号；在声称的 typed 输入范围内语义已文档化且注册表 product_wiring.document_projection=pending 诚实延期，但 V1 接线时必须由真实投影提供证据，不能以该标志冒充投影已运行（注册表已如此声明，此处留痕）。
4. 两处 normalized 解释性偏差（均为 pending 原子，raw 保留，无当前执行影响）：r03-t01-r06-investigator_center 将源句"负责开展试验的研究者"表述为"主要研究者"；r03-t05-r03-exposure_criteria 保留源词"暴露标准"（已注明改写需独立出处，V1 语义审阅时应裁定是否即"排除标准"）。

## 修复建议

无需强制修复。可选（owner 自行裁量）：V1 接线时为 projection_completed 提供投影侧证据；语义审阅时裁定"暴露标准"源义。

— 报告完。owner 验收独立进行。
