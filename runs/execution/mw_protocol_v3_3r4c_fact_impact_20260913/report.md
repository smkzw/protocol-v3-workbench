# 3R.4C 执行报告 — 带事实标签的影响计划（fact-labeled impact）

执行worker：有界3R.4C代码与功能测试。日期：2026-09-13。状态：实现完成、定向与全量回归绿；未做验收（owner独立验收）。图输出不是医学批准；3R.4整体与产品未完成。

# Execution Output:

## Boundary And Context Check

- 权威已读：`plans/mw_protocol_v3_implementation_plan_v3_20260912.md` §3R.4C 全文与 §3R.4D 接口要求；`.trellis/tasks/09-11-protocol-v3-3r4/prd.md`（含checkpoint尾部Canonical projections与A审阅处置）；`reviews/codex_mw_protocol_v3_3r4b_acceptance_20260913.md`；最新全局AGENTS与workspace AGENTS。
- 反例输入：`runs/mw_protocol_v3_3r4b_20260912/fresh_review_20260913/owner_c_reconnaissance.json`（A{x},B{x,y},C{y}，只改x时旧引擎把C一并重开，status=reproduced）。
- 只写允许路径：`services/api/app/protocol_workflow/registries/dependency_graph.py`、`tests/protocol_v3/test_dependency_graph.py`、新`tests/protocol_v3/test_fact_labeled_impact.py`、本run `runs/execution/mw_protocol_v3_3r4c_fact_impact_20260913/`。原树dirty不提交/不重置/不stash；未触碰Trellis、Plan、B的applicability/fact_bindings/chapter contracts、canonical/application、全局配置、旧runs与fixtures。
- B复用（只读import，不另造规则/事实平台）：`applicability.py` 的 `RulePredicate`/`evaluate_predicates`/`ApplicabilityStatus`/`load_applicability_rules`；`fact_bindings.py` 的 `FactBinding`/`affected_chapter_fact_paths`/`load_fact_catalog`/`_json`（canonical JSON相等，同包既有私有跨引惯例，如applicability引chapters私有函数）。
- 当前组装registry定位：config内111份authored contracts较 `runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json`（冻结历史）已有20份合同差异、743 vs 724事实词表；`interim_configuration/final_assembled.json`等中间件也落后于当前合同。故新测试按chapters既有机制从当前config组装（node_tree模板推导coverage_role+v2_front_block=cover，claim词表由当前合同+B目录推导，fixtures=[]结构用途），并用B的fail-closed装载器证明版本绑定（`load_fact_catalog` 743绑定通过、`load_applicability_rules` 70规则通过）。

## Work Performed

1. **修复事实标签丢失的过度传播（需求1、2）**：`DependencyGraph._propagate_labels` 为唯一传播引擎。标签=实际改变的事实路径集合：
   - `fact_membership`（直接事实使用）：声明改变的合同路径的章节为direct种子，携带自身标签与resolved状态；
   - `consistency_impact`（语义一致性）：只转发该边`shared_fact_paths`实际携带的已变标签——共享未变事实的章节不再被桥接重开（红测先复现`24==1`、`31==16`、反例C被误开，后修绿）；
   - `scheduling`（明确dependency_ids）：转发上游全部标签，真实扇出链式不截断；调度到达章节不伪造自身未变事实的标签，因此不会反向播种一致性传播（合成a→b→c链+共享w的d保持不受影响用例证明）。
   - `impact()` 旧诊断接口签名与返回形状保持不变，语义换新引擎；未变事实的共享边不再产生consistency桶新增（membership派生边下该桶为空是可证性质，测试固化）。
2. **新增D可消费的可执行计划入口（需求2、3、5）**：`build_fact_labeled_impact_plan(graph, *, facts_before, facts_after, bindings=(), rules=()) -> FactLabeledImpactPlan`。
   - 值保真：`_diff_fact_values` 按字面键diff，`False`≠`0`（native JSON类型保持）、同值不伪造变化、缺失键算变化而非默认false；不把点号键拆成员地址（嵌套`{"a":{"b":…}}`只报字面键`a`变化，不造`a.b`）。
   - 别名：有bindings时经 `affected_chapter_fact_paths` 做canonical→合同词表翻译（前向：canonical改→synopsis章节重开）；输入键若是bindings别名且canonical未变→仅 `ProjectionRefresh`（候选显示刷新），不进affected、不重开canonical owner（"摘要投影不反向使未变事实失效"）；映射不到合同路径的canonical变化进 `unmapped_canonical_paths` 报告而非静默全开。
   - 适用性三态：规则状态用B的 `evaluate_predicates`（before/after各评一次，规则声明缺失=不可解析）。unknown/`conditional`/缺声明→`pending_facts`，标签pending；pending-only章节= `candidate_check`，不直接失效确认，也不删除关系；pending经真实调度传播为候选。`False`永远按decisive解析不作为缺值；true义务不做章节级激活投影——共享owner逻辑仍归B的`_project_obligations`执行；`all`组合不拆单事实临床因果（disposition只按规则记录）。当前registry上interim章因plain required事实变化而章级reopen，同时其5条interim规则disposition=pending_facts（分层语义，真实规则集测试固化）。
   - 候选/确认分离：`confirmed_reopen_contract_ids`（任一resolved标签支撑）与 `candidate_check_contract_ids`（仅pending标签）分开；`entries` 逐章含 `reason`（direct_fact_use/consistency_impact/scheduling）、`via_fact_paths`、`via_contract_ids`（首次交付链）、`rule_plans`。
3. **诊断查看与可执行拒绝（需求4）**：未知依赖/缺repair owner的图照常构建（findings保留、原诊断负例未动），计划仍可查看，但 `is_executable()`=False、`require_executable()` 抛 `ImpactPlanNotExecutable`（携带findings清单）；hard cycle仍在build拒绝，双向一致性边不误判环（原测试保持绿）。
4. **投影hash定性（需求5）**：`impact_sha256` 与新 `plan_sha256` 文档+测试均定性为投影hash：剂量上调(10→20)与回退(20→10)两个必须分别采用的操作产出相同hash，证明不能作采用幂等键；D须在自己的UoW绑定base revision/operation key/实际值变化。纯函数重复调用相等不冒充采用幂等。
5. **旧断言升版（需求6）**：升版记录写入 `test_dependency_graph.py` 模块docstring，逐项：
   - `test_broad_dose_endpoint_change...`：旧行为=dose/endpoint各期望24（含一致性桥接重开），oracle `_reference_closure` 是引擎BFS的转录复制，无法发现共享缺陷；新期望=dose恰为其1个直接载体（原24全为桥接）、endpoint=4直接+6调度下游=10；新oracle `_reference_fact_labeled_closure` 从raw JSON独立不动点计算（直载+传递dependency_ids闭包，从不读一致性边），另断言传递调度下游全覆盖（真实扇出不截断）；无任何声明了已变事实的章节被丢弃，不弱化义务。
   - `test_same_fact_update_has_a_single_adoption_effect`：旧组合期望31（过度扇出），新期望16=两个事实标签闭包的并；并集性质保留；冻结值对象与单次采用效果断言全部保留。
   - 旧负向fixture、诊断负例、hard-cycle/reciprocal测试全部保留未弱化；冻结历史制品 `final_all8_assembled.json` 未改写（旧文件仍绑定它作历史锚）。
6. **当前组装registry绑定（需求6）**：新测试文件以当前config合同组装registry，断言111节点/41调度边/55一致性边/成员797-90-111/findings=0；计划版本绑定 `registry_sha256`==图、`fact_bindings_sha256`==`fact_bindings_plan_hash(catalog.bindings)`（catalog本身经B装载器对当前registry验证）、`applicability_rules_sha256` 由当前70规则digest；endpoint计划 `entries`=10=独立oracle全集（4 direct + 6 scheduling，全部confirmed_reopen）。

## Artifacts And Evidence

修改文件（sha256）：

| 文件 | sha256 |
|---|---|
| `services/api/app/protocol_workflow/registries/dependency_graph.py` | `dc39e682d13ba852a7c3e124d18b835cdcdcae2376b52ebc3a2ba3bf8cfa95f1` |
| `tests/protocol_v3/test_dependency_graph.py` | `a1e27b0b994515a1382bb3a8f6d39249185047ae2936348c26e9c6e1ea8c841a` |
| `tests/protocol_v3/test_fact_labeled_impact.py`（新增） | `4cbe4086ca251fc4511412077b044db31c2a09cfa38651ae7179c17166ac9da6` |

本run证据：`fact_labeled_red.log`（红：旧文件3失败=24==1/31==16/桥接反例C误开；新文件ImportError收集失败=计划API缺失）、`fact_labeled_green.log`（绿：26 passed）、`full_regression.log`（全量第1次：2197 passed+1顺序偶发失败，单独复跑即过）、`full_regression_rerun.log`（全量复跑：**2198 passed, 1 warning**）、`full_regression.xml`（junit，复跑前首跑生成——注：xml为首跑写入，结论以rerun log为准）。

新API签名/来源绑定/调用示例/边界（D接线用）：

```python
from app.protocol_workflow.registries.dependency_graph import (
    build_dependency_graph, build_fact_labeled_impact_plan,
)
graph = build_dependency_graph(registry_document_or_payload_or_path)
plan = build_fact_labeled_impact_plan(
    graph,
    facts_before=study_before.facts,   # Mapping[str, JsonValue]，canonical字面键
    facts_after=study_after.facts,     # 同一UoW内显式派生重算后的完整after事实
    bindings=catalog.bindings,         # B load_fact_catalog(当前fact_bindings.json, registry)
    rules=rules_catalog.rules,         # B load_applicability_rules(当前applicability_rules.json, contracts)
)
plan.require_executable()              # 图有unknown target/缺owner时抛ImpactPlanNotExecutable
plan.changed_canonical_paths / changed_fact_paths / unmapped_canonical_paths / unindexed_fact_paths
plan.entries  # AffectedChapterPlan(contract_id, reason, confirmation, via_fact_paths, via_contract_ids, rule_plans)
plan.confirmed_reopen_contract_ids / candidate_check_contract_ids / projection_refreshes
plan.registry_sha256 / fact_bindings_sha256 / applicability_rules_sha256 / plan_sha256  # 均为投影hash
```

边界：输入是canonical事实映射不是StudyDefinition对象；显式派生必须在同一UoW把重算后的y写进facts_after后再调用（不传派生map、不从`and`组合推断因果）；规则 Freshness 由B装载器在加载时hash验证；`plan_sha256`/`impact_sha256` 不是logical work key；计划不做义务投影/医学判断/采用——采用归D单UoW（复用SQLite/UoW/reservation/ledger）。

## Commands And Observations

测试环境（合同指定env）：

```
env -i PATH=… PYTHONPATH=tests/protocol_v3:services/api:packages:. \
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest <files> -q -p no:cacheprovider --tb=short
```

- 红（修复前）：`test_dependency_graph.py` 3 failed / 8 passed（`assert 24 == 1`、`assert 31 == 16`、桥接反例`contract:v2-t-c:v2`误入affected）；`test_fact_labeled_impact.py` ImportError收集失败。→ `fact_labeled_red.log`
- 绿（修复后）：两文件 26 passed（11+15）。→ `fact_labeled_green.log`
- 全量：第1次 2197 passed + 1 failed（`test_error_codes.py::test_workflow_error_survives_generator_context_cleanup`，顺序/时序偶发：单独复跑即过，且全仓无其他测试import dependency_graph——rg证据；与本改动无耦合）；复跑 **2198 passed, 1 warning**。→ `full_regression_rerun.log`
- 关键锚点（实测）：冻结制品上endpoint 24→10、dose 24→1、组合31→16；当前registry consistency边43→55、成员891→998（B修订后更多条件共享），事实标签语义下endpoint仍=10=独立oracle。
- 全程未npm install/未装依赖/未启动服务或产品模型/未递归派发。

## Blockers Or Missing Environment

无阻塞。未做事项（均属他方边界）：D接线（3R.4D，消费本计划入口）、独立review、owner验收登记；本run不改判B验收范围，不代表产品完成。

## Rerun Requests Or Next Step

- 建议owner验收C后，D按上例接线：同一UoW内 facts_before/after + 当前catalog绑定 + 当前规则 → `require_executable()` → 按 `confirmed_reopen` 实际采用、`candidate_check` 待决呈现、`projection_refreshes` 仅刷新显示；以实际SQLite效果（同key重复提交仅一份有效版本、不同revision两次不同操作）证明采用，不用函数重复调用相等冒充。
- 若D需要JSON/Mermaid图导出（plan §3R.4C可选项），当前未实现（无消费方）；需要时再按计划新增 `scripts/qc/protocol_v3/render_chapter_dependency_graph.py`。
- 全量回归中那次偶发失败若再次出现，建议按 `test_error_codes.py::test_workflow_error_survives_generator_context_cleanup` 的顺序污染单独排查（与本任务文件无import关系）。
