# E04 Worker Report — 3R.5A R03 提取脚本、criteria registry 与最小 qc 检查

- logical key: `mw_protocol_v3_3r5a_r03_20260913_v1`；declared route `zcode/zcode/GLM-5.3-Flash`（max），统一10218，7200秒预算。
- worker：单一E04执行worker，未接受任务、未递归派发/会商，未调用产品模型/服务/OCR/翻译/Word，未访问凭证或生产库。
- 状态：**terminal，交付待owner验收**。本报告不构成任务接受或医学验收。

## 1. 交付物（5个允许文件，全部新增）

| 文件 | SHA256 |
|---|---|
| `scripts/qc/protocol_v3/extract_r03_criteria.py` | `9e8487321dc0d6d7723a09888719daf49e535a956ad44ec3ad517ba5afe1d34a` |
| `config/medical_writing/protocol_v3/qc/r03_criteria.json` | `c9dd46257ba54776e5ebc831c214a51e0fe5f00c2936f04220b27daeb1129c2f` |
| `services/api/app/protocol_workflow/qc/__init__.py` | `5c98a91c6b2b0c436ed9261047001cca465567307ea66e065bc113f8ca9d1d2d` |
| `services/api/app/protocol_workflow/qc/r03.py` | `59f8169b0a3ad8180d98eb73d6ef6163ef8419e3c02a2a82f573352bf3b4b28e` |
| `tests/protocol_v3/test_r03_criteria_registry.py` | `398781aac496c790d0ac2206fcf46852e5ea07375d4b2b75635eb1482af8eefd` |

源未改动：`CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx` 交付前后 SHA256 均为 `5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9`（zip/XML只读）。未commit/reset/cleanup，未改既有A-D代码/类型/配置/测试/word/terminology（git status中既有M文件为owner并行工作，本worker未触碰）。

## 2. 分母

**源分母**（生成时双重校验，与审计基线一致）：17物理表、104物理行 = 4身份行 + 32重复表头行 + 68内容行；T5/R0/C1表头内嵌招募义务单独fragment（不算第69行、不随表头丢失）。签署段落（`body/paragraph[39]`，含孤立字符"2"按源保留）登记为合法空白控件。

**atom分母**：129条原子义务 = 4身份atom + 124条覆盖68内容行（每行≥1，复合行拆分）+ 1表头fragment atom。
- 按类别：deterministic 14 / agent4 109 / human 6（human复用2个共享确认ref：`confirm_contact_entities`、`confirm_signature_authority`，未造68张卡）。
- 按状态：**implemented 5 / pending 124**（见§4）。
- flags：source_noise 2 / reference_hint 2 / source_ambiguity 1 / header_embedded 1，全部保留在分母内。

## 3. 提取器与registry（交付1、2）

- `extract_r03_criteria.py`：纯标准库（hashlib/zipfile/xml/json/argparse/tempfile），`verify_source_hash`源hash门 + 分母漂移即失败；行定位零基`table/row/cell`，保留`grid_span`/`vMerge`（restart/continue）、空E6 label、合并单元格、原始段落文本。行提取与审计基线`r03_source_rows.json`逐字段相等（测试断言）。atom_id=`r03-t{tt}-r{rr}-{sub_key}`（+`r03-t05-r00hdr-*`），不用6.x label作键；source_label从实际行C0逐字附着（含"6.1.2 "尾空格、"6.4.0"、空label）。生成时自检：raw_fragment必须是源行子串（空白归一后）、语义节点在当前node_tree（`v2_front_block`经front_block特判）、rule_ref在applicability_rules.json、噪声串不进normalized字段、内容行全覆盖。
- 典型拆分（可核对）：6.3.2 estimand→7 atoms（五属性+population_summary映射v2_n_3_1_2_4按审计注明+consistency）；6.5.3→3情形矩阵7 atoms；6.8.5→委员会3（rule `applicability:n-14-7:oversight-charter`）+AE随访/特定事件随访2（**always，不因无委员会关闭**）；6.4.11 CtQ→7；6.13数据治理→7；6.9.6 SAP→3（批准安排=将来安排，normalized不含"已批准"）；6.9.2样本量→4；6.11→6；6.10→2。
- 噪声/歧义：6.16乱码（"Lal…"）与"试验目的和目的"、"DescrIDescription"等保留在raw source；normalized字段生成时自检不含噪声串。"排斥反应"行标`source_ambiguity`+`unknown_context`，不改写为妊娠/过敏等（禁词断言在测试中），不当普遍门槛。6.5.2保留源词"暴露标准"。器械行/IIT行conditional+not_wired，不当false也不作普遍缺陷。
- 适用条件：引用已登记规则ID共12处（如front-1:amendment、n-7-2:randomization、v2_n_4_5:blinding/emergency、v2_n_4_2:placebo、n-8-1:individual-hold/hold-to-stop、n-6-1-2:dose-modification、v2-n-11-4-9:interim、n-14-7:oversight-charter、front-4:service-parties、n-3-1-2-4:strategy-crosscheck），loader校验ID真实存在；其余显式`not_wired`并注明"未知不当false"。无任何atom被评not_applicable（无研究事实不裁决，测试断言）。

## 4. 六项L1登记与最小qc.r03（交付3、4）

| L1 | 状态 | 说明 |
|---|---|---|
| 版本四点一致 | **implemented（typed输入）** | `check_version_consistency`：当前位置不一致→`r03_version_inconsistent`；修订历史旧行不比对（合法保留，测试断言）；当前字段空→error；空材料fail-closed |
| 文字性交叉引用 | **implemented（typed输入）** | `check_internal_citations`：以明确目标对象清单解析，缺目标→`r03_citation_target_unresolved`；目标重复→error；空材料（无引用且无目标=投影未跑）fail-closed；合法无引用（有目标清单）通过 |
| 缩略语闭环 | pending | 需从实际正文生成并绑定权威术语条目，非空字符串不判正确（3R.7接线） |
| 文献双向 | pending | 双向闭合≠证据仍适用，不用年份阈值冒充时效性验收 |
| 数字单位 | pending | 数值复算需绑定研究事实投影 |
| 登记一致性 | pending | 先核实实际登记源与版本，未登记不得生成"已登记一致"回执 |

- 复用语义：检查结果即现有`FixtureCheckResult`（subject_id/chapter_contract_id=`r03_qc_registry`/findings/`deferred_qc_obligations`=四个pending L1 id），finding即现有`CheckerFinding(code/severity/location/message)`，无新数据库/框架。
- 产品接线诚实声明：registry `product_wiring` 明确 generation_model/word_export/ui_consumers=`not_wired_v1`、document_projection=`pending`；`wired_checks`仅两项且wiring=`typed_input_only`。Atom层面仅5个implemented（4身份atom+6.1.1标识atom→version检查）；t04-r15 IIT引用虽为引用类atom仍标pending（适用条件未接线，注明"接线前不对真实文档运行"）。
- registry loader（`validate_r03_registry`/`load_r03_criteria`，Pydantic typed document）：校验源hash、分母与行实测一致、atom_id重复、locator存在、raw_fragment子串、语义节点、rule_ref存在、未知检查实现引用、implemented⇒check_ref、内容行全覆盖、表头fragment、签署区、六L1齐备、wired_checks与实际函数一致；问题列表非空即`R03RegistryError`fail-closed。只做图/源计数可靠性，不判医学充分性。

## 5. 红绿测试证据（交付5）

命令：`python3.12 -m pytest tests/protocol_v3/test_r03_criteria_registry.py -q`（python3.12；pytest 3.14环境无pytest）。

1. **红**：仅测试文件存在时 `47 failed in 0.48s`（提取器/registry/qc模块均不存在）。
2. 实现过程中两轮部分绿：`10 failed, 25 passed`→修复导入引导（`registries/__init__`要求`app.`绝对导入，测试引导root+services/api入sys.path）、ROOT层级（parents[5]）、碎片atom断言等。
3. **绿**：`47 passed`（log存run目录`test_log_green_final.txt`）。全程未xfail/降expected；未改任何既有fixtures/测试。
4. 确定性：`python3.12 scripts/qc/protocol_v3/extract_r03_criteria.py --check`再生成与提交字节一致（log `determinism_check.txt`）；测试内另断言两次tmp生成互等且等于提交文件。
5. 反例覆盖（真实行为，非"文件存在"）：无label行、表头内嵌义务、复合行拆分（estimand/退出矩阵/委员会/CtQ/数据治理/SAP）、未知/条件不当false、当前版本不一致→失败、历史旧日期→允许、引用目标缺失/空材料→失败关闭、源错词不污染normalized（"Lal/试验目的和目的/DescrIDescription"断言）、签署空白非草稿、loader六类破坏（重复/未知节点/未知检查/implemented无ref/源hash/未知rule）均被拒。
6. 共享面无扰：`PYTHONPATH=services/api python3.12 -m pytest tests/protocol_v3/test_chapter_fact_binding.py -q` → 51 passed。未跑全量protocol_v3（按dispatch避免影响并行独立工作）。

## 6. 问题与修正（实际发生）

- 提取器`:=`语法错、`_atom`签名与调用不一致：修正。
- 噪声自检初版把"note"也列入禁列，但note是溯源说明（需点名噪声串）：收窄到normalized_check/evidence_requirement，与测试一致。
- 排斥反应atom首版把禁词枚举写进normalized：移至note，normalized只描述义务。
- 测试sys.path需同时容`app.`与`services.api.app.`两条导入根；`qc/r03.py`仓库根定位改parents[5]。
- 测试自身两处粗糙变更（applicability_rule_refs注入、criteria[-1]假设）在红阶段修正为真实行为变更。

## 7. 诚实边界（未声称）

- 本registry是结构化登记（`registered_not_accepted`），**不是已接受医学registry**：逐atom医学充分性、适用性按研究事实的裁定、人工确认执行均未发生；注册≠通过。
- 两个implemented检查只对typed输入负责；真实文档投影、生成模型、原生Word/UI消费者、全量对象核对属V1/V1.5，未接。
- 未运行产品模型/Word/服务；未做全量protocol_v3回归；文件数不作为通过依据，分母/ID/绑定/引用由loader与测试实际校验。
- 未更新Trellis；owner验收、fresh reviewer核对原源与冻结registry后方可关闭。
