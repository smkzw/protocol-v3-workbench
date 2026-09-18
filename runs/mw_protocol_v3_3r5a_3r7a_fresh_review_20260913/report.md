C03 独立评审完成。完整报告已存 `runs/mw_protocol_v3_3r5a_3r7a_fresh_review_20260913/reviewer_scratch/C03_review_report.md`，以下为全文要点。

# C03 独立来源/工程评审 — 3R.5A / 3R.7A（冻结快照 20260913）

**结论：PASS（限于本次 ENGINEERING/SOURCE 声称范围）**。未发现 P1/P2 缺陷；已实现范围内全部关键声明经独立复现成立；V1/V1.5 未实现边界在制品内诚实登记、未冒称。评审过程只读（scratch 外零写入）、未启动 Word/服务/模型调用、未读执行方 worker 报告。

## 哈希与制品一致性（非 LLM 锚点）

- 两个源 docx SHA256 与合同一致（5a5affeb…／018d28d3…）；manifest 自身哈希与 dispatch_contract 记录一致；快照 252/252 文件哈希逐一核对通过、无多余文件；当前树 252 文件与快照全部一致（在当前树执行测试的前提成立）。
- **字节级再生成**：用快照提取器从冻结 docx 重新生成 `r03_criteria.json`（410346cd…）与 `word_source_objects.json`（98338306…），与提交件 `cmp` 完全相同——两注册表是确定性源驱动制品，非手工拼装。

## Scope A（R03）

- 我用自写脚本独立解包源 DOCX 提取：17 表／104 物理行／4 身份行／32 表头行／68 内容行（54+14），与注册表 denominator 一致；104 行文本与 gridSpan/vMerge 结构逐行交叉比对 **0 差异**。
- T5/R0/C1 表头内嵌招募义务单独保留（raw 含杂引号，原子 r03-t05-r00hdr-recruitment_method，不计入 68 分母、未随表头丢失）；签署段落 body/paragraph[22] 经独立核实为唯一匹配。
- 129 原子全矩阵审阅：68 行全覆盖、复合行拆分可追溯、14/109/6 类别分布、implemented 原子均绑定真实检查。语义陷阱逐项核实：排斥反应保留原词（source_ambiguity，不改写为过敏/妊娠）；AE 随访 always（委员会不免除）、特定事件随访独立且未知未决；SAP 批准为将来安排；IIT/CSR 为 reference_hint 非普遍义务；“Lal／试验目的和目的／DescrIDescription”等源噪声只留 raw 不进 normalized；旧 6.x 标签仅作 source_label。
- `qc/r03.py` 两检查：空/纯空白材料 fail-closed、修订历史旧行不参与比较、caller subject 全路径保留、引用按显式目标清单解析、`projection_completed` 区分零引用已评估范围与未投影。六项 L1 单独登记且只有两项标 implemented（typed_input_only），与实际相符。

## Scope B（Word 源对象）

- 316 书签＋290 域全部映射，无 32 项上限（40 项反例）、无成功交集过滤（合成 missing/ambiguous 反例保留为 findings）；当前源 13 种 required styles（实际 styleId）与 172 个 required bookmark 确实全部存在，findings=[] 是真实状态。
- 外部文档 HYPERLINK＋本地片段 → external_document_anchor，不误记为内部缺失书签；源 XML 多余 bookmarkEnd（314/321，孤儿 7 个）作为 source 观测保留且 scope 明示非生成文档验收；`native_word_invoked=false`；required_cross_references 仅 1 条如实登记。

## Scope C（术语/占位修正）

- 三消费者（content_quality 逐块、ai_task_runner `_validate_protocol_full_draft_output`、full_draft `adopt`）均接共享 `iter_unresolved_draft_markers`；全仓 grep 确认无残留原始正则直接消费。合法执行句（未同意不筛选／确认后锁库）不误判，同段同格真待确认仍定位。
- “受试者”仅 warning（公司偏好非禁令、不自动替换、引用标题保留原文且强制 source_locator）；全角单位/百分号仅警示不换算；半角 μg 与方案编号/版本/日期串不误报（探针复核）；缩略语按实际使用清点、full_form_review=not_performed；签署空白合法但不豁免草稿/模板说明。旧负向 fixture（“<0}”、传输词、待医学经理确认等）expected 原样保留。

## 测试与局限

- 隔离 venv 决定性测试 8 个文件：**95 passed / 0 skipped**（含真实 DOCX 对照），命令与日志见报告文件；reviewer 独立反例探针 10 组（`reviewer_scratch/independent_probes.log`）。
- 局限：未跑完整 protocol_v3 套件（按合同）；未启动 Word/渲染（V1.5）；注册表医学充分性未评估（制品自声明 registered_not_accepted 与事实相符）。**模型独立性受限**：执行方 Flash 与本评审 GLM-5.3 同提供商家族，已用哈希核对、字节再生成、逐行独立提取、测试复跑等非 LLM 锚点补偿。

## P1/P2/P3 发现

**P1：无。P2：无。** P3（观察项，无需修复即可交付）：

1. `dispatch_contract.json` 记录的 route_manifest_sha256（ef297ff3…）≠ 当前 `scheduled_route_manifest.json`（168dadd1…）；系 07:15:57 off_peak 评估重写路由清单所致（内容与本次路由相符），过程性记录差异，不影响三 scope 制品。
2. 执行条款豁免为整子句全匹配：带限定词的合法变体（“若受试者未提供书面知情同意书，则不进入筛选。”）仍被报占位（probe 1 复现）；方向保守（转人工、不产生假通过），与代码注释取舍一致。
3. `projection_completed` 为调用方声明信号；typed 范围内已文档化且注册表诚实延期，但 V1 接线必须由真实投影提供证据，不得以标志冒充投影已运行。
4. 两处 normalized 解释性偏差（pending 原子、raw 保留、无当前执行影响）：investigator_center 将“负责开展试验的研究者”表述为“主要研究者”；exposure_criteria 保留源词“暴露标准”（V1 语义审阅应裁定是否即“排除标准”）。

**修复建议**：无强制项。可选：V1 为 projection_completed 补投影侧证据；语义审阅裁定“暴露标准”源义。Owner 验收独立进行。
