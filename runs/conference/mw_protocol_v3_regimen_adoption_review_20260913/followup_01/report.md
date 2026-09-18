先读本次修复复核合同与新制品清单，再只核 A/B/C 三项，不重做整包审阅。先核 11 个当前文件的哈希，并对照 owner 回归日志与改动源码。哈希已对齐。接下来写独立反例：核对 424 是否写前失败、lookup 是否不重编译，以及前端是否误标 busy/当前批准。# Conference Output: mw_protocol_v3_regimen_adoption_review_20260913 - evidence_single_object

## Output

同会话修复复核（followup_01）。只挑战 A/B/C。11 文件哈希初核/终核均为 11/11 匹配。原 P1（完整来源 read-set、Study 父绑定、RecommendationOption/ClaimEvidenceLink、当前确认有效性）仍未实现，本次代码未把它们伪装成已完成，也未在这四项上倒退。

**有限接受该修复：可以。** 不是产品/医学/Word 最终验收。

---

### Evidence

**哈希**  
`followup_01/artifact_manifest.json` 11 路径 SHA-256 初核与终核 mismatch=0。只写了 `followup_01/scratch/`。未改旧 scratch、未改产品。

**A. 配置错误 424 vs 未知 500，且确为写前失败**

源码：
- `_status_for`：`P1_SERVICE_CONFIGURATION_INCOMPLETE` → 424（`api/router.py` 168–172 行）。其它非 retryable 仍 500。
- 公开包仍四字段（`errors.py` 455–463、294 行）：`message/responsible_area/can_retry/next_step`。配置文案含「未执行」「请修复工作台配置后继续。」
- `apply_decision` 仅在 `ledger.find(cas_id) is None` 后、`build_and_apply` 前加载模板（`service.py` 483–512、577 行）。

独立探针 `test_a_template_missing_is_424_before_any_write`（venv python，tmp SQLite，fake opener）：
- 先创建 study，再打爆 `load_current_template`，并包裹 `EventSourcedUnitOfWork.build_and_apply`。
- adopt **424**；recover **404**；dump 与 `event_stream/aggregate_revision` 计数相对创建后不变（12/1/1）。
- 调用顺序 **`["load"]`**，没有 adopt 路径上的 `"write"`。
- detail 仅四公共字段，`can_retry=false`，message=`工作台配置尚未就绪，本次操作未执行。`
- 日志：`followup_01/scratch/probe_a_424.json`

未知负例原样：`test_unknown_operation_response.py::test_unknown_operation_requests_reconciliation_before_retry` 与探针 `test_a_unknown_failure_remains_500` 均为 **500**，「尚未确认」+「勿重复提交」。

前端 A（`RegimenAdoptionCard.jsx` 86–93、15–18、46–47、67–71、116 行）：
- 424 写 `key:not-executed` = operation_id，保留原 intent，不自动 recover/adopt。
- 重开若 marker 匹配则 `configurationRejected`，只显示「配置恢复后继续保存原选择」。
- 继续保存复用**同一** intent/CAS，仅按钮点击。
- 独立探针：重开 0 次 recover、0 次自动 adopt；点继续后第二次 adopt body 与第一次相等。500 路径仍是「核对本次确认」，没有配置重试钮。

**B. `lookup_decision` 不重编译、不加载模板**

- HTTP recover 走 `prepare_regimen_recovery` → `lookup_decision`（`design.py` 86–93 行）。
- `prepare_regimen_recovery` 只用已存 `output_sha256` 重建 DecisionRecord，**不**调用 `propose_regimen_fact_updates`，无 ready_for_review 闸（`study_definition.py` 78–88 行）。无 output_sha → None → 404。
- `lookup_decision`：ledger CAS + 事件里 operation/CAS 对齐 + DecisionRecord `material_sha256`；返回 **current definition + 原 effect**（`service.py` 626–655 行）。无 template、无 fact 再编译、无 `replay_or_apply` 写。

独立探针：
- 采用后另写无关事实到 rev3，再打爆 compiler 与 template：lookup **200**，`revision==3`，`replayed=true`，原 `decision_record_id` 保留，后继 age 仍在，dump 不变。
- 改 reason：**409**。
- 错误 run id：**404**。
- `needs_information` 且无回执：adopt 409，lookup **404**（不再是初轮的 422）。
- 破坏最后一条 event 的 `kind`：lookup **500**（进度不一致），不是 200。`probe_b_corrupt.json`。

既有 `test_regimen_adoption_api.py`：未决 lookup 404；compiler RuntimeError 仍 200；篡改 reason 409。

**C. 底部回执 / 待核对不误称 busy 或当前医学批准**

- 待核对：`confirmationBlockedReason="本次提交待核对，请先找回原确认记录。"`，`busy` 仅在途请求（`RegimenAdoptionCard.jsx` 110–114 行）。
- 回执：标签「监管答辩级·确认记录」、按钮「原确认记录已保存」、说明「原确认记录已保留；后续研究修改的有效性以当前研究版本为准。」（`RegimenProposalCard.jsx` 179、191、238 行）。
- 既有+独立前端：待核对时空「正在处理中，请稍候。」；回执后无「监管答辩级·需确认」；424 重开无「本次选择已保存」。

**命令与计数（不以 owner 日志代替）**

```text
PYTHONPATH=services/api:tests:tests/protocol_v3:tests/protocol_v3/integration:.
PYTHONDONTWRITEBYTECODE=1
runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest -p no:cacheprovider \
  tests/protocol_v3/test_unknown_operation_response.py \
  tests/protocol_v3/integration/test_regimen_adoption_api.py \
  tests/protocol_v3/integration/test_template_fact_adoption.py::test_exact_replay_after_template_unavailability_replays_without_loader \
  followup_01/scratch/probe_followup01_abc.py
cd frontend && ./node_modules/.bin/vitest --environment jsdom --run \
  RegimenAdoptionCard.test.jsx RegimenProposalCard.test.jsx
cd frontend && ./node_modules/.bin/vitest --config ../.../followup_01/scratch/vitest.config.mjs --run
```

| 批次 | 结果 |
|---|---|
| 独立 A/B pytest | 5 passed |
| unknown + template 424 | 5 passed |
| 既有 adoption API（含在首次合并跑） | passed |
| owner vitest 两文件 | 17 passed |
| 独立前端探针 | 2 passed |

Owner 三份 regression.log 为旁证，不替代上述源/反例。

---

### Inference

1. **A 达到合同。** 424 是模板加载失败且 `build_and_apply` 未进入 adopt；不是换了个标签的 500。未知路径仍 500。前端把 424 记成未执行、重开不按未知提交去 lookup，配置恢复后显式同 CAS 再提交。
2. **B 达到合同。** lookup 与 apply 闸门分离：未决无回执 404；篡改 DecisionRecord 材料 409；后继不回退；错误 run 不假成功；腐坏 ledger 500 停机而不是伪造回执。
3. **C 达到本修复范围。** 待核对不再借用 busy 文案；回执改称「原确认记录」并指向当前研究版本，不把历史回执说成当前医学批准。
4. **原 P1 未在本 11 文件中被悄悄「完成」。** `prepare_regimen_adoption` 仍只绑 `intervention.dose_regimen`；App 仍未传 study/actor（本清单无 App.jsx）；仍无 RecommendationOption/ClaimEvidenceLink 行。

残留脚注（不否决有限接受）：`recover_decision` 旧编译路径仍留在 service，HTTP 已不用。lookup 不核对 `fact_updates_sha256`（刻意，因不再编译）。卡片主状态仍有「本次选择已保存」，但标签/按钮/免责已改，不构成 C 失败。

---

### Recommendation

**有限接受 A/B/C 修复。** 可并入该冻结采用单元的配置分类、只读回执查询与回执文案。

不要登记：当前确认有效、完整来源 read-set、Study 父绑定、选项/证据链持久化、真浏览器采用、整稿/Word。

下一步仍按初轮未决，不在本修复上重开全项目 review。

---

### Uncertainty

- 未跑真浏览器、真模型、OCR、live 服务。
- 腐坏 ledger 只破坏最后一条 event 的 `kind`；其它腐坏形态未穷尽。
- 并发双飞 424/采用未测。
- `recover_decision` 若被其它入口再调用，会回到旧编译语义；当前 design router 未调用。

非主席，不宣布产品/医学/Word 最终验收。
