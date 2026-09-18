# 3R.4D Worker Report — 当前模板事实采用接线（E04）

> **Follow-up 01 补记（owner adoption cases 修复后）**：本报告以下正文为 round-1 状态。owner acceptance 三个探针失败后已在同一会话修复，详情、最终 hash、残余缺口见 `owner_followup_01/report.md`。要点：(1) 撤回正文"兼容性说明"中"模板变更后同 key replay 得 409"的 allowance——现 ledger-first 以请求级意图指纹分类，相同请求在模板漂移/loader 不可用下仍精确 replay（0 次 loader 调用、零写入），变更请求仍 409；(2) apply 路径强制同 idempotency key 仅一个逻辑操作（新 decision 复用 key → 409 零效果），create 侧保留 owner 冻结语义；(3) inactive 校验改为全量结果态，并实现 `retired_fact_paths`（由 `retired_alias_paths` 更名扩展）显式退役：alias 映射 + genuinely-inactive 受控事实（unknown 不是 inactive，active shared owner 优先）。最终：owner 探针 3/3 passed（`worker_owner_cases_check.json`）、本套件 18 passed、定向 316 passed、全量 `tests/protocol_v3` **2234 passed**（`worker_full_protocol_v3_followup.log`）。正文中的旧 hash/旧行为描述以 follow-up 报告为准。

- logical_work_key: mw_protocol_v3_3r4d_template_adoption_20260913_v1
- worker: E04 GLM-5.3-Flash:max，统一句柄会话内执行；无递归派发、无会商、无模型/路由替换
- base: dispatch_contract.json 16 个 base hash 与工作树逐一核对一致（owner 冻结 D 内核）
- 本报告只写本轮新证据；未自行验收、未改 Trellis/Plan/live/8910/旧 runs

## Execution Output

## Boundary And Context Check

- 完整重读 /Users/smkzw/.codex/AGENTS.md、workspace AGENTS.md、Plan v3 3R.4D 及 20260913 接线细化、design v1.4 尾部三节（错误分类/输入绑定/采用兼容）、Trellis 09-11-protocol-v3-3r4 checkpoint 尾部、reviews/codex_mw_protocol_v3_3r4c_integration_readiness_20260913.md。
- Owner 已完成部分未重做：errors.py 404/配置错误分类、ApplyStudyDecisionCommand 的 revise_confirmed_facts + decision_input_refs、decision_inputs.py 三态 current/stale/unverified、reconstruction 新 operation、template_runtime.load_current_template。进入前对 16 个 base hash 逐一生效核对（全部一致）。
- B（fact_bindings/applicability）与 C（dependency_graph）源码只读，本轮零修改；其真实接口按 readiness 绑定使用：build_fact_labeled_impact_plan(graph, facts_before, facts_after, bindings, rules)、build_applicability_snapshot(contracts, study, rules, created_at)。当前模板实测 111 contracts / 743 bindings（13 alias、21 boolean）/ 70 rules（0 pending），无 presence 冲突，允许直接使用既有 snapshot 构造器。
- 允许文件外的写入：无（application/queries.py、application/__init__.py、canonical/document.py、graph/runtime.py、B/C 源均未触碰）。

## Work Performed

1. 新增 `application/adoption.py`（typed 接线核心）：
   - `TEMPLATE_FACT_ADOPTION_SCHEMA="template-fact-adoption.v1"`、`TemplateAdoptionValidationError(kind, fact_paths, detail)`。
   - `prepare_template_adoption`：装载后 identity echo 核对（template_id 不匹配拒绝）、退役意图目录级校验（仅 confirmed alias 可退役）、预建 dependency graph、生成 CAS adoption material（模板身份 + 排序退役清单）。
   - `validate_retirement_presence`（fresh-only、ledger 判定后、reducer 前调用，保证 exact replay 永远 ledger-first）与 `validate_adoption_facts`（采用后状态）：null 值不是 delete、B `_typed_value` 原生类型校验（字符串 "false" 不得冒充布尔）、alias/canonical 全目录一致性（矛盾不静默裁决）、三态条件矛盾（全 owner not_applicable 且有实际值 → 拒绝；unknown/缺失保持未决允许部分保存）、退役必须真实存在于 facts_before 且已从 facts_after 移除。
   - `TemplateAdoptionFlow.validate_and_build_payload`：同一事务内在 CAS 写之前生成完整 adoption payload = base/result revision+hash、facts before/after hash、字面变更路径、退役清单、B ApplicabilitySnapshot（111 entries，unknown=未决）、C 完整 FactLabeledImpactPlan（confirmed_reopen 与 candidate_check 分开、findings/unmapped/unindexed/projection_refreshes 全量保留）、registry/catalog/rules 身份（template_sha256、registry_sha256、registry_binding_sha256、rules digest、绑定/规则计数）、operation key `template_fact_adoption.v1`。
   - `verify_template_adoption_payload`：事件自足复验（base/result 绑定、双 facts hash、变更 diff 重算、退役移除、snapshot 绑定 adopted revision、plan↔identity 交叉绑定）。
   - `literal_fact_diff` / `impact_plan_payload` / `GetTemplateAdoptionQuery` / `TemplateAdoptionQueryResult`。
2. `registries/template_runtime.py`：新增 `default_template_root()`、`applicability_rules_digest()`（与 C plan 的 rules digest 同构，二者在 payload 内相等，可交叉复验）、`template_identity()`（全部由 source-bound 装载物计算，不接受客户端自报身份）。
3. `canonical/study_definition.py`：`TEMPLATE_FACT_ADOPTION_OPERATION` 常量；`_fact_updates_sha256` 新增 adoption-material 分支（模板身份+退役+updates+refs 全部进 CAS material；历史无 material 路径逐字节不变）；`replay_or_apply`/`apply_decision` 新增 `retired_fact_paths`、`adoption_material`；`_merge_facts` 支持显式移除（退役需要显式 confirmed revision intent、路径必须存在、FROZEN 一律拒绝）。
4. `application/service.py`：构造函数新增可选 `current_template_loader`（缺 loader 且命令带模板意图 → SERVICE-CONFIGURATION_INCOMPLETE；装载失败 → `_CurrentTemplateUnavailableError` → 同码，不提示重新确认推荐）；apply_decision 接线：意图预准备（replay 分类之前、不依赖状态）→ ledger-first replay → fresh 时状态意图检查 → reducer → validate_and_build_payload（任何拒绝在 CAS 写之前）→ payload["operation"]/payload["template_adoption"] 同事件持久化 → build_and_apply 原子提交；新增只读 `get_template_adoption`（事件重建最新 adoption 记录、身份绑定复验、零写入零模型调用）；_translate 新增 TemplateAdoptionValidationError → D1_STUDY_DEFINITION_INCOMPLETE（retryable，audit_context 带 kind+paths，HTTP 409）。
5. `application/reconstruction.py`：接受 `template_fact_adoption.v1`；adoption 事件必须携带完整 payload、非 adoption 事件携带 payload 即拒；重建时按事件内 retired_alias_paths 复原移除并 `verify_template_adoption_payload` 复验全部 hash 绑定。
6. `application/commands.py`：`TemplateAdoptionIntent(retired_alias_paths, template_id echo)`；命令新增 `template_adoption` 字段，携带意图时强制 `revise_confirmed_facts is True`。
7. API：`schemas.py` 新增 `TemplateAdoptionIntentRequest`、`TemplateAdoptionIdentityResponse`、`TemplateAdoptionResponse`，apply 请求新增可选 `template_adoption`；`router.py` 传递意图并新增 `GET /study-definitions/{id}/template-adoption`（无记录 404 中文包）；`composition.py` 挂载时注入 `load_current_template(default_template_root())` loader（每次采用现装载、不缓存、legacy 命令不触达）。用户不手填 JSON/hash/read-set；UI 只需自动附 template_adoption 对象。
8. 新增 `tests/protocol_v3/integration/test_template_fact_adoption.py`：14 个用例全部走真实 mounted composition（真实当前模板 tp_ma_07_v2）+ 真实 product SQLite + HTTP，tmp 隔离、合成项目。

红线义务（有意不做）遵守：未建第二文档保存链、未改 canonical/document.py、未把 plan_sha256 当 work key/idempotency、未删旧负例/fixture、未 xfail。

## Artifacts And Evidence

新增/修改（均为允许文件；SHA256）：
- services/api/app/protocol_workflow/application/adoption.py（新）786d8121dc2e5c5d61d8941143e1e0339c3a89faee178f716c1b3f6d7d76f2d4
- services/api/app/protocol_workflow/registries/template_runtime.py f82498b2d0c1e4acafddb175edc88d32f7e8b0beba3568829efa7c4d4d481220
- services/api/app/protocol_workflow/application/service.py 634a0accf2305a7b36d790f7c8d18b839b0a0857fc550754849c6c5d237bac61
- services/api/app/protocol_workflow/application/commands.py c8715797ac813b9a1ec4a51367b87b9c2ea6e441d6f2c77ba0d81182a309c386
- services/api/app/protocol_workflow/application/reconstruction.py 127fbad2dd11b23ec8dc6291ff81e0340e544c6acb760c90e46c09cdfc047cd3
- services/api/app/protocol_workflow/canonical/study_definition.py b83bcc3824c717bf6b361c2e1d6073521dce4afe38c8759743db4a3f1943966f
- services/api/app/protocol_workflow/api/schemas.py 889338abf1bc336b065a455a4798e668eb6c4152fbd0a28695338d8dc8d309d5
- services/api/app/protocol_workflow/api/router.py 99566021846f40c8b1591a03b70ea53c14e64b5821fc658e09a50dee5b0c8c86
- services/api/app/protocol_workflow/api/composition.py 61bd989b302f957d368533f1d9e781bcb9678fd9b3c7c05426a082562b69d5d6
- tests/protocol_v3/integration/test_template_fact_adoption.py（新）507fa43281812586f3fc2268e68ba2fab085867fcf0e365c5e9f87d74d604803

未触碰核对：errors.py=2bd7ef07…、ports/repositories.py=ba221f7b…、test_fact_impact_adoption.py=93a7b4a4…、test_current_template_runtime.py、test_decision_input_binding.py、test_study_definition_reducer.py、test_study_event_reconstruction.py 全部仍等于 dispatch contract base hash。

日志（本 run 目录）：
- worker_template_adoption_red.log：实现前 14 failed（422 extra-forbid / 路由缺失，行为反例）
- worker_full_protocol_v3.log / worker_full_protocol_v3_final.log：全量 2230 passed（cleanup 编辑前后各一次，均 0 failed）

## Commands And Observations

环境（每轮一致）：clean env PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. TMPDIR=$(getconf DARWIN_USER_TEMP_DIR)，python=runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python。

- `pytest tests/protocol_v3/integration/test_template_fact_adoption.py`：红 14 failed → 绿 **14 passed (3.54s)**。
- 定向回归：integration/ + reducer/reconstruction/decision_input/current_template/application_service/decision_cas/error_codes = **192 passed**；api_contract + dependency_graph + fact_labeled_impact + chapter_fact_binding + chapter_applicability + agent5 = **438 passed**。
- 全量 `pytest tests/protocol_v3`：**2230 passed, 1 warning, 0 failed (54s)** ×2。

API 调用示例（实际链路，TestClient over mounted composition）：
```
POST /api/projects/{p}/protocol-workflow/study-definitions/{sd}/decisions
{
  ...既有 apply 字段..., "revise_confirmed_facts": true,
  "fact_updates": {"statistics.sample_size.interim_applicable": false},
  "decision_input_refs": [{"fact_path": "contact.sponsor_organization"}],
  "template_adoption": {"template_id": "tp_ma_07_v2",
                        "retired_alias_paths": ["synopsis.sponsor"]}
}
GET /api/projects/{p}/protocol-workflow/study-definitions/{sd}/template-adoption
→ 200 {base/result revision+hash, facts hash, changed_fact_paths, retired_alias_paths,
       template{template_sha256, registry_sha256, registry_binding_sha256,
                applicability_rules_sha256, 743/70 counts},
       applicability_snapshot{111 entries, unknown=未决}, impact_plan{confirmed_reopen vs candidate_check}}
（无记录 → 404 中文包；GET 前后 iterdump 相同）
```

验收场景→证据（均在真实 SQLite 上断言）：
1. 既有 canonical 值→新值（contact.sponsor_organization rev2→rev3，非新增路径）✓
2. 同 key exact replay 零新 aggregate/event/outbox（iterdump 逐字节相同）✓
3. 同 path 新 key 两次不同 revision 有效 ✓；同 key 不同意图（退役意图/模板身份 echo）拒绝 ✓
4. 并发 CAS 一胜一待处理（败者 409+can_retry+刷新指引，胜者可查询）✓
5. 字符串 "false" 对 boolean 绑定拒绝、原生 False 通过；null 不是 delete ✓
6. alias/canonical 矛盾阻止；同值对齐允许；显式退役解锁；退役后旧 revision 原样保留（get_at_revision rev3 仍含 alias）✓
7. 退役意图类型化限制（canonical/未目录/absent 均拒）；仅退役无更新是合法显式移除 ✓
8. not_applicable 条件与实际值冲突阻止；unknown 条件允许部分保存且 snapshot 记未决 ✓
9. 事件重建：新存储连接 reconstruct_study 复原 revision hash 与事实，且 adoption payload 全部 hash 绑定复验通过；retirement-only 事件也能重建移除 ✓
10. 相关确认 stale/无关 current/legacy unverified + Agent5 队列仅 stale 再入队 ✓
11. 旧 legacy 命令在 adoption 存在后仍精确 replay（零写入、零模板依赖、adoption 记录不移动）✓

兼容性说明：`_fact_updates_sha256` 新分支仅在 adoption_material 非 None 时生效；无模板意图请求（含全部历史事件）hash/序列化逐字节不变（errors/reducer/既有测试全绿佐证）。模板文件在原始采用与 replay 之间变更时，同 key replay 得到 409（意图材料不再相同）——这是有意 fail-closed，重试需按原字节重发。

## Blockers Or Missing Environment

- 无阻塞。运行环境、venv、当前模板源均按合同可用。
- 未做（按 dispatch“有意不做”）：整稿采用去重与有效文档版本保存（V1 6R/7R 与编辑器同实现，义务保留未验收）；R03/Word/UI/生成 Agent 接线；未对文档原绑定做任何同步显示改动。
- 本轮为工程接线证据，非医学/内容/产品验收；3R.4 冻结独立 review 与 Codex 登记验收仍归 owner。

## Rerun Requests Or Next Step

- 无需重跑。owner 可直接读本 run 的 diff/hash/两份全量日志与红灯日志进行冻结与独立 review。
- 若 review 需要：单个用例可复现命令 `pytest tests/protocol_v3/integration/test_template_fact_adoption.py::<name>`（环境变量同上）；全量复跑一次 ~54s。
- 建议后续（V1，非本轮）：编辑器自动附 template_adoption 上下文时，template_id echo 建议总是携带，以便模板升版后旧客户端得到明确拒绝。
