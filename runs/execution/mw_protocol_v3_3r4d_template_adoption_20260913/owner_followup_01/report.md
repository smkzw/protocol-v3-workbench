三个 owner 探针全部通过（未改动探针），全量 2234 passed。续作完成，报告在 `runs/execution/mw_protocol_v3_3r4d_template_adoption_20260913/owner_followup_01/report.md`，不自行验收 D。

# Execution Output:

## Boundary And Context Check

重读当前全局 AGENTS 与原 prompt/contract；允许路径与用户边界不变；无递归派发、无产品模型/服务、无 live 写、未动 Trellis。Owner 探针文件按原样运行，其 .py sha 不变（da3dc88f…）；探针自身设计会重写输出 JSON，owner 原始失败记录 JSON 已按原字节恢复，本轮通过输出另存 run 目录。

## Work Performed

1. **探针1（历史 replay 装载模板/loader 不可用 422）**：CAS material 重构为**请求级意图指纹**（operation + template_id echo + retired_fact_paths + fact_updates + input refs），全部可从请求与事件 payload 复算、零 I/O；当前模板装载移入 fresh-apply 分支（ledger 证明无记录效果之后）。相同请求在模板漂移/loader 不可用下精确 replay（0 次 loader 调用、零写入、successor revision 保持）；变更请求（含 echo 变化）仍 409；真正的新采用在模板不可用时归 SERVICE-CONFIGURATION_INCOMPLETE（500 配置类，调用点再包分类保护）。模板身份仍在采用时强制核验并持久化；`_rebuild_ledger` 现以 `recompute_adoption_intent_sha256` 从记录内容复算 intent hash 并比对——绑定记录内容而非字段存在。**撤回 round-1 报告中“漂移后同 key replay 得 409”的 allowance**（与用户合同冲突）。
2. **探针2（同 key 新 decision 再次写入）**：apply 的 fresh 路径新增 `_reject_reused_idempotency_key`——本聚合事件流同 key 不同 CAS identity → IdempotencyConflictError → 409 零效果；无 side_effect 也生效；重启（新 mount）后同 key 同 decision 仍精确 replay。create 侧不加此检查：owner 冻结测试定义的 P1_REVISION_STALE fail-closed 语义原样保留（该测试不在允许文件，其拒绝+零效果结果不变）。
3. **探针3（flag true→false 残留旧 adjustment）**：inactive 校验改为**全量结果态**——所有规则受控路径在采用后事实上评估，全 owner not_applicable 且有实际值（false/0 也是值）→ 409 零效果；unknown 保持未决不阻止部分保存。同时实现 owner follow_on 要求的**显式解决方案**：字段更名 `retired_alias_paths` → **`retired_fact_paths`**（更名理由：语义从仅别名扩展到受控事实，旧名误述能力；字段为本会话新增、owner 探针经我方 helper 构造不受影响），允许退役 confirmed alias 映射与 genuinely-inactive 受控事实（unknown 不是 inactive、任一 applicable shared owner 即拒绝）；canonical 真值/目录外路径永不可退役；null 仍不是删除；历史 revision/事件逐字节保留。复用既有 reducer，未改 B/C 科学规则。

## Artifacts And Evidence

- 最终 hash（全部在允许清单内）：adoption.py 36a2da62…、service.py 9c738311…、commands.py 3f15612d…、reconstruction.py d5077881…、schemas.py cefccf2c…、router.py ad1a94b8…、test_template_fact_adoption.py 15fc8e74…；study_definition.py/template_runtime.py/composition.py 本轮未改（hash 同 round-1）；errors.py、ports/repositories.py 仍等于 owner 基线。
- `test_template_fact_adoption.py` 18 passed：新增 4 个探针回归（replay 免装载+变更冲突+fresh 500、同 key 新 decision+重启 replay、条件关闭拒绝+显式退役解决+历史/重建/replay、退役需 genuinely inactive+unknown 部分保存）。
- `worker_owner_cases_check.log/.json`：未修改的 owner 探针 **3/3 passed**；定向回归 316 passed；全量 `worker_full_protocol_v3_followup.log` **2234 passed, 0 failed**。

## Commands And Observations

环境同合同（clean env + Darwin TMPDIR + 项目 venv）。探针运行：`python owner_adoption_cases.py` → 3/3 passed（replay 200+replayed+0 loader 调用+SQLite 不变；同 key 409+不变；flag off 409+不变）。API 语义示例：`"template_adoption": {"template_id": "tp_ma_07_v2", "retired_fact_paths": ["statistics.sample_size.interim_adjustment"]}` 与 `fact_updates={"…interim_applicable": false}` 同一次采用内显式关闭并退役，历史 revision 2 仍保留原值。

## Blockers Or Missing Environment

无阻塞。残余缺口（详见 follow-up 报告）：shared-owner 退役组合无真实模板自然用例（all-not-applicable 判定已强制）；ledger 复算仅覆盖 adoption 事件（owner 既有 operation 公式不动）；create 侧错误族归 owner 裁定；本轮为工程证据，D 验收归 owner。

## Rerun Requests Or Next Step

无需重跑。owner 可读 `owner_followup_01/report.md`、`worker_report.md` 补记、探针通过输出与全量日志进行冻结与独立 review；单用例复现 `pytest tests/protocol_v3/integration/test_template_fact_adoption.py::<name>`。
