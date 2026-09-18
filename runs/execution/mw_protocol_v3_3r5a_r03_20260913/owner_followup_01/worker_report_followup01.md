# E04 Worker Follow-up Report 01 — 3R.5A R03 failed-acceptance修复（4项）

- logical key `mw_protocol_v3_3r5a_r03_20260913_v1`，同一session续跑，declared GLM-5.3-Flash:max。状态：**terminal，待owner fresh-review**；状态保持`registered_not_accepted`；未接受/关闭任务，未改Trellis 3R7A锚点。
- 修复依据：`owner_first_verification.json`（5 hash核对通过）与`runs/mw_protocol_v3_3r5a_source_audit_20260913/r03_candidate_empty_probe.json`（before/after hash=59f8169b…，与本次修复前qc/r03.py一致；blank_version/blank_citation原passed=true为实际缺陷）。

## 1. 修复内容与理由

1. **空白身份字段**（原缺陷：四字段全`'  '`+相同位置→passed=true）：`check_version_consistency`改用`_is_blank`（strip后为空=缺失），报`r03_version_field_empty`并逐字段点名；原始字段值在finding中逐字引用不改写；有意义当前值与历史版本（含带空白的旧值）行为不变。理由：空白表格不构成身份通过；probe实证假通过。
2. **引用/目标空白字段与零引用范围区分**（原缺陷：text/target_id/kind全空→passed=true）：新增拒绝码`r03_citation_text_blank`/`r03_citation_target_blank`/`r03_citation_target_kind_blank`；`R03CitationMaterial`增加最小显式`projection_completed: bool=False`信号——默认空输入=未投影→`r03_material_missing`（旧行为不因新信号翻成pass）；显式声明完成+零引用范围→passed且不虚构目标；声明完成不豁免空白字段或未解析目标（dirty用例验证）；既有合法"有目标清单+零引用"路径保留可用。属文档完整性检查，无安全工程。
3. **subject_id错挂**（原缺陷：两检查收subject_id但`_result`恒返`r03_typed_input`）：`_result`透传subject_id，成功与每个早期失败路径（None/空投影/空白字段）均保留调用方身份（probe复现证据含subject断言）。
4. **r03-t08-r06-specific_event_followup适用性科学修正**（原缺陷：与AE随访同被断言为always）：AE随访保持always；特殊事件（妊娠等）随访改为`conditional`+`rule_ref=None`+`not_wired`，条件为研究自身相应事件适用性；委员会独立性（设置不替代/未设不免除）保留在normalized_check；evidence_requirement改指研究事件适用性事实；未复用避孕排除等无关规则、未虚构事件规则ID；源义务/atom未删（129分母不变）；registry不声称已执行运行时适用性判定。旧断言按owner指示作为documented scientific correction更新，并新增"两条随访义务均不绑定委员会章程规则"断言。

## 2. 红绿证据

命令：`python3.12 -m pytest tests/protocol_v3/test_r03_criteria_registry.py -q`

- 红（仅改测试后）：`5 failed, 46 passed`（4新用例+委员会修正断言；`projection_completed`触发ValidationError属预期红），log `test_log_red_followup01.txt`。
- 绿（实现修复+重生成registry后）：`51 passed in 0.50s`（净增4项），log `test_log_green_followup01.txt`。
- probe复现（`probe_repair_evidence.txt`）：blank_version→`passed=False`（`r03_version_field_empty`）；blank_citation→`passed=False`（text/target/kind三个空白码）；`projection_completed=True`零引用→`passed=True`无findings且subject_id=doc-9透传。
- 确定性：`extract_r03_criteria.py --check`再生成与提交字节一致（`determinism_check_followup01.txt`）。
- 源hash复验：`5a5affebd36979cb06e9…`未变。

## 3. 变更后hash（本轮实际改动3个产品文件；`qc/__init__.py`未动，hash不变）

| 文件 | 新SHA256 | 变化 |
|---|---|---|
| `scripts/qc/protocol_v3/extract_r03_criteria.py` | `868a0dd4e9306ffb02db284d967655768739f52426e03406e654985e8d15b45e` | 改 |
| `config/medical_writing/protocol_v3/qc/r03_criteria.json` | `410346cd00b98ab1cf19b1c961be11efad1a30120ee5662a8b794f6223926bed` | 重生成 |
| `services/api/app/protocol_workflow/qc/r03.py` | `ac7080e2581b46f4af591d5d20657e4964642c02f9a535e7246c1e91298c428a` | 改 |
| `services/api/app/protocol_workflow/qc/__init__.py` | `5c98a91c6b2b0c436ed9261047001cca465567307ea66e065bc113f8ca9d1d2d` | 未变 |
| `tests/protocol_v3/test_r03_criteria_registry.py` | `14a4681d1f6f1f2bfb213d099e3d534ff5051ccdfb4b7979f55224b64b55a46a` | 改 |

首轮产物保留：`worker_report.md`、`test_log_green_final.txt`、`determinism_check.txt`、`deliverable_sha256.txt`、`report.md`、`runtime_receipt.json`及owner候选工件均未覆盖。

## 4. 当前计数与状态

- 分母不变：17表/104行=4身份+32表头+68内容；129原子=4身份+124内容行+1表头fragment；类别14/109/6；状态implemented 5/pending 124；六L1：2 implemented（typed输入）/4 pending。
- `product_wiring`与全部诚实边界不变：两检查仅对typed输入负责；生成模型/Word/UI为V1；医学充分性、运行时适用性判定、人工确认未执行。

## 5. 局限

- `projection_completed`是调用方声明信号，本阶段无法从typed输入本身证明投影真实运行；误声明属调用方责任，registry不冒称已验证投影。
- 特殊事件随访的条件为声明性（not_wired），无运行时判定；未知未决不当false。
- 未跑全量protocol_v3、未做产品调用（按contract）；文件数不作为通过依据。
