# 3R.4C owner_followup_01 — 受控义务共享owner语义修复

同会话定向修复（原bounded worker）。日期：2026-09-13。首轮report/receipts保留在run根目录未覆盖；本轮证据全部在`owner_followup_01/`。仍不验收、不闭任务；产品写仅3个允许文件+本run。

# Execution Output:

## Boundary And Context Check

- 先读最新全局AGENTS；原prompt全部范围与纪律继承。只写`dependency_graph.py`、`test_fact_labeled_impact.py`、本run的`owner_followup_01/`；`test_dependency_graph.py`本轮无改动（hash与首轮一致）。未触碰B/canonical/application/Trellis/Plan；未运行产品模型/服务；未递归派发；未再探测产品连接。
- owner证据（只读）：`runs/mw_protocol_v3_3r4d_preflight_20260913/c_owner_cases.py`（带真实合成合同hash，可直接执行）与`c_owner_cases.json`。两例均按owner描述在本轮修复前精确复现（见`owner_cases_reproduce_before_fix.log`）。
- 当前registry真实声明核对：`applicability_rules.json` 70规则共控制94个`conditional_fact_paths`；`statistics.interim.applicable`、`picos.primary_endpoint`、`picos.intervention_dose_regimen`、`safety.central_lab_applicable`、`intervention.dose_regimen`均不在控制集合内，故首轮真实registry测试期望不受本次语义修正影响（实测保持绿）。

## Work Performed

1. **修复错误1（受控基础required被早返回绕过）**：`_label_resolved`不再对FACT_REQUIREMENT无条件早返回。声明事实只有在同合同没有规则经`conditional_fact_paths`控制它时才是无条件（且合同存在未声明executable predicate的规则时不能证明无条件，保守按受控处理——当前registry 0 pending，无实际影响）。受控required的决断权交给控制规则owner状态。
2. **修复错误2（共享owner语义颠倒）**：owner决断改为镜像B已验收的`_project_obligations`语义：任一owner applicable→义务确定active（shared active owner wins，即使同字段其他owner conditional/missing）；全部owner resolved not_applicable→确定released（旧内容仍须刷新，不丢失释放事实）；无applicable且存在未决owner→undecided（pending→candidate_check），从不把unknown当false。when_active与受控required同用该owner决断；trigger路径按规则自身resolved状态决断；规则声明缺失（None）不阻断applicable-wins，但使"全部released"不可判。owner状态按章节自身合同规则计算（`rules_by_contract`），不受调度或其他章节影响。
3. **顺带修复覆盖通道**：`_propagate_labels`一致性边送达不再提升接收章节对已声明路径的标签决断状态（共享路径必为双方声明，决断权留在本章节）——owner要求"调度或同一字段的其他章节不得覆盖本章节条件判定"。调度边保持真实扇出（上游重开→下游必须重跑），但下游rule_plans仍按自身规则计算。
4. **owner反例纳入正式期望测试**（`test_fact_labeled_impact.py`新增7例，先红后绿）：
   - `test_owner_case_controlled_base_requirement_unknown_is_candidate`（owner case 1：candidate_check）；
   - `test_owner_case_shared_active_owner_wins_over_unknown`（owner case 2：confirmed_reopen，且rule:a stable/applicable、rule:b pending_facts分层并存）；
   - `test_owner_release_refreshes_stale_content`（触发true→false释放：confirmed_reopen+obligation_change，旧内容刷新）；
   - `test_owner_all_inactive_and_active_inactive_owner_combinations`（全部inactive可决断→confirmed_reopen；active+inactive→applicable wins→confirmed_reopen）；
   - `test_owner_all_unknown_owners_stay_candidate`（全部unknown→candidate_check）；
   - `test_unconditional_fact_still_reopens`（纯无条件fact仍重开）；
   - `test_consistency_and_scheduling_never_override_own_conditional_decision`（a自身规则unknown保持candidate；b自身owner applicable为confirmed_reopen；一致性边与调度依赖均不翻转a的判定；b的rule_plans仍按自身规则）。
5. **B小纯函数提议（未越界改B，仅提议）**：为消除决断表在两模块的重复，建议B在`applicability.py`暴露纯函数，例如`def owner_decision(states: Sequence[ApplicabilityStatus]) -> Literal["active", "released", "undecided"]`（applicable∈states→active；states非空且全NOT_APPLICABLE→released；否则undecided），并让`_project_obligations`的removed/inactive计算与C的`owners_decided`共用。B未改；当前C侧本地镜像已按B验收语义实现并在docstring标注来源。

## Artifacts And Evidence

本轮修改文件（sha256）：

| 文件 | sha256 | 变化 |
|---|---|---|
| `services/api/app/protocol_workflow/registries/dependency_graph.py` | `eb75dc674a4ee18bee08e501b77ae6422aa349d38992d49e8980361de742efc4` | 首轮`dc39e682…fa95f1`→本轮 |
| `tests/protocol_v3/test_fact_labeled_impact.py` | `b274086096faed2818cbf9e3fdc3579041296e9965e979eb0c549556d2a51524` | 首轮`4cbe4086…c9da6`→本轮（+7例） |
| `tests/protocol_v3/test_dependency_graph.py` | `a1e27b0b994515a1382bb3a8f6d39249185047ae2936348c26e9c6e1ea8c841a` | 与首轮一致，无改动 |

本轮证据（均在`owner_followup_01/`）：`owner_cases_reproduce_before_fix.log`（修复前owner脚本输出：case1=confirmed_reopen错、case2=candidate_check错）、`owner_cases_red.log`（新7例红：3 failed/19 passed，恰好锁定两owner错误+覆盖通道）、`owner_cases_after_fix.log`（修复后owner脚本输出：case1=candidate_check、case2=confirmed_reopen，与owner期望一致）、`fact_labeled_green_followup01.log`（两C文件33 passed）、`b_targeted_green.log`（B定向330 passed）。

## Commands And Observations

- 修复前owner脚本复现（合同env）：case1 `confirmation=confirmed_reopen`（应candidate）、case2 `confirmation=candidate_check`（应confirmed_reopen）——与owner判词一致。
- 红：`test_fact_labeled_impact.py` 3 failed/19 passed，失败正是`827: 'confirmed_reopen' == 'candidate_check'`、`844: 'candidate_check' == 'confirmed_reopen'`、`965: 覆盖守卫confirmed_reopen应candidate`。
- 修复后：两C文件**33 passed**（11旧+22新）；`test_chapter_applicability.py + test_chapter_fact_binding.py + test_compact_dependency_contract.py` **330 passed**（B语义/绑定无回归）。
- 按owner指示本轮**未跑全仓**（owner的D红测↔修复与全仓回归读写交叉风险）；未改旧日志。

## Blockers Or Missing Environment

- **首轮判断纠正**：我首轮将`test_error_codes.py::test_workflow_error_survives_generator_context_cleanup`失败判为"顺序偶发"不成立。owner当时在disjoint D文件执行红测试→修复，恰与全仓回归重叠造成确定性读写交叉；`context_cleanup_red.log`+代码修复证明是确定性问题而非随机失败。旧日志保留作历史；此纠正以本轮为准。
- 首轮"2198全仓通过"不对应现在最新固定源（owner其后加入显式事实修订路径），不能作为当前源的全仓结论引用。
- 未决事项：①B侧`owner_decision`纯函数提取未实施（越界，待owner/共享owner裁定，见上文提议）；②全仓联合验证归owner在两部分冻结后执行；③D接线消费仍未开始（3R.4D）。

## Rerun Requests Or Next Step

- 建议owner复核`owner_cases_after_fix.log`与7个新期望测试；确认后按计划冻结C侧，由owner在其D工作与C侧均冻结时联合全量验证。
- 若owner接受B侧`owner_decision`提议，最小改动为applicability.py新增纯函数+C侧`owners_decided`改为转调（一轮定向测试可覆盖），本轮未执行。
- D接线时注意：受控字段的confirmed_reopen/candidate语义已按共享owner规则；D仍须在同一UoW做实际采用（本计划仍是投影，非采用）。
