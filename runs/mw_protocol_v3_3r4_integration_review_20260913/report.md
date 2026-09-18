所有证伪实验与隔离测试完成。整理最终中文报告。

---

# Protocol v3 3R.4 A–D 接线独立审阅报告（fresh review，run: mw_protocol_v3_3r4_integration_review_20260913）

## verdict

**PASS（仅工程3R.4 A–D接线范围内）**。32项独立证伪探针全部通过，未发现P1/P2缺陷；3项P3观察记录如下，不阻塞工程验收登记。无最终产品验收、医学、UI、模型、Word声明。

## inspected_artifacts

- **hash核对**：`artifact_manifest.json`绑定365个文件（源码/配置/测试/Plan/design），对实际工作区逐一SHA256核对——0缺失、0不一致。后续所有执行均在该同hash工作区进行。
- **通读源码**：`application/adoption.py`（670行）、`application/service.py`（1379行）、`application/reconstruction.py`、`application/commands.py`、`canonical/study_definition.py`（reducer/CAS/ledger）、`canonical/decision_inputs.py`、`canonical/hashing.py`（关键段）、`registries/applicability.py`、`registries/fact_bindings.py`、`registries/dependency_graph.py`、`registries/template_runtime.py`、`api/composition.py`、`api/router.py`（关键段）、`events/unit_of_work.py`（事务顺序段）、`storage/sqlite.py`（schema段）。
- **测试**：`tests/protocol_v3/integration/test_template_fact_adoption.py`（857行全文）、`test_fact_impact_adoption.py`、`integration_shared.py`、`test_mounted_api_integration.py`装配段。
- **配置**：`applicability_rules.json`（70规则、`pending_rule_ids`为空、94条受控路径、其中8条多owner共享）、`fact_bindings.json`（743绑定、17别名、类型分布boolean 21/json 713/object 8/string 1）、模板目录。
- **Plan/design**：`mw_protocol_v3_implementation_plan_v3_20260912.md`与`mw_protocol_v3_design_v1.4_20260912.md`全文，含2026-09-13三项细化与D验收反例补实条款。

## findings

无P1/P2发现。P3观察（均不阻塞，不建议本轮改动）：

1. **P3（观察，非缺陷）`consistency_impact`通道在当前图构造下构造性不可达** — `registries/dependency_graph.py:1327-1340`（一致性边由共享事实成员成对派生）与 `:563-667`（传播引擎）。任何共享了变更路径的章节本身就是direct seed，一致性投递对已持标签路径被显式跳过（`:644-649`），调度到达的章节也不能为未声明事实播撒标签。合成图与真实模板（S4.5，sponsor变更仅产生1条`direct_fact_use`条目）均未出现该类条目。合同要求的反例行为（A{x}B{x,y}C{y}变x不误开C）已满足；该枚举值当前是防御性/前向兼容通道。风险：若后续有人把“一致性传播扇出已激活”当作已验事实，将与实际不符。
2. **P3（观察）集成测试夹具事实路径不在743词表/canonical宇宙中** — `integration_shared.py:25-29`的`picos.intervention.dose`、`picos.population.age`在`fact_bindings.json`中无对应绑定（真实规范路径为`picos.intervention_dose_regimen`等）。此类事实采用成功（事实库是权威）、影响计划记入`unmapped_canonical_paths`且entries为空（S4.6证实为显式追踪而非静默），符合Plan 3R.4A“尚不支持字段有明确清单”。含义：这些测试验证的decision-graph stale/current完全由`decision_input_binding`驱动，不经由影响计划。测试语义成立，引用者需知此边界。
3. **P3（观察）错误码枚举字符串含重复段** — `errors.py:108-110`，`P1_CHECKPOINT_EVENT_MISMATCH`的值为`"MW-PRO-P1-CHECKPOINT-CHECKPOINT_EVENT_MISMATCH"`（CHECKPOINT双写）。行为正确（S5.4实测按此码拒绝篡改事件），值已进入稳定错误契约，不建议本轮修改。

**D→V1义务边界确认**：整稿版本采用（“同key仅一份有效文档版本”）按Plan 2026-09-13接线顺序细化明文移至V1的6R/7R集成任务；本轮制品未声称完成该义务，也无代码路径冒充（`SemanticDocumentReducer`无整稿应用消费者，D接线只在StudyDefinition事务内绑定事实/输入/条件快照/影响/事件）。该义务既未失败也未被标记完成——与合同要求一致。

## counterexamples_and_tests

证伪脚本：`runs/mw_protocol_v3_3r4_integration_review_20260913/reviewer_scratch/falsify_3r4.py`（结果JSON同目录），真实挂载链+隔离临时SQLite，解释器`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`，`PYTHONDONTWRITEBYTECODE=1`、无cache、零fixture改动。命令：

```
env -i PATH=... TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3/integration:tests/protocol_v3:services/api:packages:. \
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python \
  runs/mw_protocol_v3_3r4_integration_review_20260913/reviewer_scratch/falsify_3r4.py
```

**32/32通过**，要点（均独立于既有测试构造）：

- **S1 replay/CAS/意图（6项全过）**：采用A→legacy后继B→精确重放A：`replayed=true`、revision保持B的后继3、全库iterdump零变化；同CAS三元组去掉adoption意图→409零写；同三元组改retirement意图→409零写；同idempotency key新decision→409零写（事件数仍3）；4个GET端点逻辑零写；重放路径0次调用`_load_current_template`（计数器证实ledger-first）。
- **S2 原生类型/字面点号（7项全过）**：`DecisionInputRef(fact_path="a.b", members=("c",))`读`facts["a.b"]["c"]`=5而非`facts["a"]["b"]["c"]`=999（字面键不拆分）；false/0/"false"/null/缺失在输入绑定中5个互异hash；`current_input_validity`：False保持current，0/null/缺失均stale，无关变更current；`literal_fact_diff`把False→0识别为变化、同值零变化；真实模板boolean绑定拒绝`"false"`与`0`（两拒均发生在revision未动时，排除stale干扰）、原生`False`采用成功且值保持`false`；对不存在路径写null→409（null不是创建/删除）；alias迁移后规范与别名两键并存同值直到显式退休。
- **S3 条件冲突/退休（8项全过）**：flag=true同时种入两条受控参数（adjustment+alpha）后仅翻转flag→409（两条参数均不在本次命令写入，阻断本身证明校验的是完整结果事实）；同事务flip+retire两条→200、事实移除、`get_at_revision`保留历史值；pk/pd适用共享owner下退休`endpoint_linkage`→409；pd未知的混合owner退休→409；全部owner不适用时**写入**实质值本身被`inactive_conditional_conflict`拒绝（我构造的反例被正确阻断）；合法路径（active种入→一次事务flags关闭+退休）→200。
- **S4 带标签传播（6项全过）**：合成图A{x}B{x,y}C{y}+调度边A→D+一致性对D-E{z}：仅变x→A=confirmed_reopen、B=candidate_check（其owner规则未声明）、**C不在entries**、D经scheduling到达；变x+y→C仅带标签{y}、无x泄漏；零值变→空计划；调度扇出到达D但D不能为未变的z向E播撒标签；真实模板sponsor变更→entries类型化、reopen/candidate互斥且并集等于entries；未映射夹具事实变更→记入unmapped且entries=0。
- **S5 事务/并发/重建/序列化（6项全过）**：真实SQLite中CAS save之后注入event append失败→异常抛出且aggregate/event行数零变化（同一UoW回滚）；双线程同revision竞争→恰一胜（rev2）一败（`MW-PRO-P1-REVISION-STALE`）、事件数2；adoption事件从零重建出已提交revision hash；篡改事件`fact_updates`内容（保留hash字段）→ledger重建以`P1_CHECKPOINT-CHECKPOINT_EVENT_MISMATCH`拒绝（回读证实篡改可见）；篡改`result_revision_sha256`→重建outcome被quarantine；`_fact_updates_sha256`五个分支（legacy空/legacy更新/带refs/显式修订/adoption）互异，legacy空分支等于`material_sha256({})`，tuple与JSON往返list的adoption意图hash一致。

**隔离重跑既有证据**：绑定集`test_template_fact_adoption.py`+`test_fact_impact_adoption.py`→23 passed；相邻A/B/C/D面（dependency_graph/chapter_applicability/chapter_fact_binding/decision_input_binding/fact_labeled_impact/decision_cas/event_replay/current_template_runtime/application_service）→484 passed。全量2234未重跑（合同允许，执行证据仍以worker记录为准）。

## remaining_uncertainty

- B目录按合同未重开70个医学源窗口；以`load_current_template`的源绑定互hash校验（catalog↔registry、rules↔contracts）、70/743数量核对与相邻测试通过替代，仅证明目录内部一致绑定，非医学内容复审。
- `consistency_impact`非空案例未在真实registry上观察到（基于构造性分析+局部验证，未穷举所有可能图形态）。
- 并发CAS为双线程单库实测（一胜一冲突）；更高并发/多进程/长时压测及非SQLite后端（memory/selected）不在本轮。
- GET零写以逻辑dump与行数为证；未做字节级/WAL物理快照对比。
- 全量回归2234未重跑；上述结论限定于本轮审阅的365文件hash冻结点。

## acceptance_scope

本verdict仅覆盖工程3R.4 A–D接线：typed事实（含false/0/null/缺失/字面点号/别名）、三态适用性（70规则/111合同/743绑定源绑定校验）、带事实标签影响计划（confirmed_reopen/candidate_check分离、桥接不误开）、真实SQLite一次采用事务（CAS/幂等key/意图hash/事件/重放/重建/退休/输入绑定current-stale-unverified）。不包含：UI、真实模型调用、Word生成、医学正式批准、整稿版本采用（V1 6R/7R义务保留且不得因本PASS标记完成）、生产切换、安全专项（USER_EXCLUDED）。最终3R.4验收登记由Codex依本报告决定。
