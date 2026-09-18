3R.4D 接线完成。模板上下文采用已真实接入现有 ApplicationService/SQLite 事务：14 项新验收全绿（红灯先行存证）、定向回归 630 passed、全量 `tests/protocol_v3` 2230 passed 两次（含清理编辑后定案）。报告在 `runs/execution/mw_protocol_v3_3r4d_template_adoption_20260913/worker_report.md`，未自行验收、未改 Trellis。

# Execution Output:

## Boundary And Context Check

- 完整重读全局/工作区 AGENTS、Plan 3R.4D 及 20260913 接线细化、design v1.4 尾部、Trellis checkpoint 尾部、3R.4C readiness。进入前 16 个 dispatch contract base hash 与工作树逐一核对一致（owner 冻结 D 内核，未重做 owner 工作）。
- B/C 源码只读、零修改；按 readiness 绑定消费真实接口（`build_fact_labeled_impact_plan`、`build_applicability_snapshot`）。当前模板实测 111 contracts / 743 bindings（13 alias、21 boolean）/ 70 rules（0 pending），允许直接用既有 snapshot 构造器。
- 允许文件外零写入（queries.py、`__init__.py`、document.py、B/C 源均未动）。

## Work Performed

1. **新增 `application/adoption.py`（接线核心）**：`prepare_template_adoption`（identity echo 核对、退役意图目录级校验、CAS adoption material=模板身份+排序退役清单）；`validate_adoption_facts`（B `_typed_value` 原生类型校验——字符串 "false" 拒绝；null 不是 delete；alias/canonical 矛盾不静默裁决；全 owner not_applicable 且有实际值才拒绝、unknown 保持未决允许部分保存）；`TemplateAdoptionFlow.validate_and_build_payload` 在 CAS 写之前生成完整 payload（base/result revision+hash、facts 双 hash、字面 diff、B ApplicabilitySnapshot 111 entries unknown=未决、C 完整 impact plan confirmed_reopen/candidate 分开、registry/catalog/rules 身份、operation key `template_fact_adoption.v1`）；`verify_template_adoption_payload` 事件自足复验全部 hash 绑定。
2. **template_runtime.py**：`default_template_root` / `applicability_rules_digest`（与 C plan rules digest 同构、payload 内可交叉复验）/ `template_identity`（全部 source-bound 计算）。
3. **reducer**：adoption-material 进 CAS material（历史路径逐字节不变）；`retired_fact_paths` 显式移除（需显式 confirmed revision intent、路径必须存在、FROZEN 拒绝）。
4. **service**：可选 `current_template_loader`（缺 loader/装载失败 → SERVICE-CONFIGURATION_INCOMPLETE，不提示重新确认推荐）；flow 在 replay 分类前只做无状态准备，ledger-first 保证 exact replay 不被模板装载拒绝；新增只读 `get_template_adoption`（零写入）；`TemplateAdoptionValidationError → D1`（409+audit_context 带 kind/paths）。
5. **reconstruction**：接受新 operation、按事件内退役清单复原移除、逐事件复验 adoption payload 全部绑定；**API**：apply 请求可选 `template_adoption`、新增 `GET .../template-adoption`（无记录 404 中文包）、composition 注入现装载 loader——API 实际可调用整条链（所有用例走 mounted composition + 真实模板 + 真实 SQLite）。

## Artifacts And Evidence

- 10 个文件（8 改 2 新，均在允许清单）：hash 见 `worker_report.md`；errors.py/ports/全部既有测试仍等于合同基线 hash（未弱化任何旧负例）。
- 日志：`worker_template_adoption_red.log`（实现前 14 failed 行为反例）、`worker_full_protocol_v3.log`/`..._final.log`（2230 passed ×2）。

## Commands And Observations

```
POST .../study-definitions/{sd}/decisions   （+ "template_adoption": {"template_id": "tp_ma_07_v2", "retired_alias_paths": ["synopsis.sponsor"]}, revise_confirmed_facts: true）
GET  .../study-definitions/{sd}/template-adoption  → 200 完整 adoption 记录 / 404 中文包 / iterdump 前后相同
```
环境：`env -i PATH=… PYTHONPATH=tests/protocol_v3:services/api:packages:. TMPDIR=$(getconf DARWIN_USER_TEMP_DIR)` + 项目 venv。结果：14/14 绿（3.54s）；定向 192+438 passed；全量 **2230 passed, 0 failed (54s)** 两次。

## Blockers Or Missing Environment

无阻塞。按 dispatch 有意不做：整稿版本保存（V1 6R/7R，义务保留）、R03/Word/UI、document.py 未动。本轮是工程接线证据，非医学/内容验收；3R.4 冻结独立 review 归 owner。一个已记录的 fail-closed 语义：模板文件在采用与 replay 之间变更时，同 key replay 得 409（意图材料不再相同，需按原字节重试）。

## Rerun Requests Or Next Step

无需重跑。owner 可直接读 diff/hash/日志冻结并做独立 review；单用例复现 `pytest tests/protocol_v3/integration/test_template_fact_adoption.py::<name>`（环境同上），全量 ~54s。
