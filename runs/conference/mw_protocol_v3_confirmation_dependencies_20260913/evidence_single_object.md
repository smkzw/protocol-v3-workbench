The reproduction confirms both the defect and the proposed semantics. All evidence is in hand — every frozen file read, hashes verified, allowed tests green, defect and remedy proven with the real primitives. Now I'll compose the complete advisory report.

# Conference Output: mw_protocol_v3_confirmation_dependencies_20260913 - evidence_single_object

## Output

### 0. 结论（先行）

- **缺陷成立且已用真实代码复现**：给药确认的事件绑定包含 `all_facts` 读集引用，`get_decision_graph` 把整个临床事实字典的任何变化（含后来终点/样本量卡片写入的事实）都映射为 `current_validity=stale`，即使已采用剂量及其直接依据完全未变（scratch 复现 A1/A2）。
- **推荐一条最小连贯路线**：在采用事件上**新增**一个独立的 `confirmation_binding`（确认依赖绑定），由服务端声明的、hash 绑定模板的逐决策范围表物化而成；现有 `decision_input_binding`（生成读集证明 + 重放 CAS 材料）语义原样保留。读路径优先使用 `confirmation_binding`，旧事件无缝回落到现行为。该方案用现有已验证原语（`DecisionInputRef` + `bind_decision_inputs` + `current_input_validity`）即可表达，`canonical/decision_inputs.py` 零改动，9 个已冻结单测原样通过。
- **最重要未决科学决策（非工程）**：范围表中医学相关/不相关的逐路径分类内容必须由医学 owner 作者化并审阅；机制不代替该判断。这是给 Codex 的显式待决项，不是本审阅能替答的。

### 1. 验证证据（hash、测试、复现）

- **14/14 冻结 hash 全部核对通过**（`runs/conference/mw_protocol_v3_confirmation_dependencies_20260913/artifact_manifest.json`，SHA-256 逐一比对，无一 mismatch/missing）。
- **允许的两支定向测试通过**：`PYTHONPATH=services/api:.:tests:tests/protocol_v3:tests/protocol_v3/integration` + 指定 venv 运行 `test_decision_input_binding.py` 与 `test_regimen_confirmed_study_input.py` → **9 passed**。
- **窄 scratch 复现**（`runs/conference/mw_protocol_v3_confirmation_dependencies_20260913/scratch/scope_reproduction.py`，仅调用真实 canonical 原语）：
  - A2：采用后新增 `statistics.sample_size.reproducible_result` 与 `endpoints.primary_efficacy` → 现行绑定 `stale`（而 A1 证明剂量三要素未变）。
  - B1–B4：提议的 confirmation binding 对“后来卡片采用/自改/删除已分类无关路径”保持 `current`。
  - B5–B9：相关路径变化（期别翻转、regimen 成员变化、相关路径删除、源资料更新）与 **B7 未分类新键** 均保持 `stale`（保守未知语义保留）。
  - 读集绑定在所有场景仍翻 `stale`（生成输入新鲜度语义未被削弱）。

### 2. 现行机制的 source:line 事实（证据）

1. **生产者读集**：`agent2/study_input.py:10-12` `clinical_study_facts` 仅排除 `research.input_context`/`research.regimen_producer` 两个记账键；`bind_regimen_study_input`（:29-45）把全部临床事实深拷贝进 prepared request 的 `confirmed_study`，并计入 run 逻辑身份。
2. **新鲜采用门**：`study_input.py:15-26` `validate_regimen_study_input` 在 fresh adoption 前做目标 study 与临床事实的**精确相等**校验（`design.py:266-271` 将违反映射为 409）。
3. **确认引用构造**：`agent2/study_definition.py:37-44` — 三条 `fact` 范围引用 + 当 `confirmed_study` 存在时追加 `DecisionInputRef(fact_path="clinical-read-set", scope="all_facts", excluded_fact_paths=(两个记账键))`。
4. **绑定存储**：`application/service.py:572-575` 在事件 payload 写入 `decision_input_binding = bind_decision_inputs(command.decision_input_refs, new_def.facts, revision_hash)`。
5. **读路径**：`service.py:885-908` 从事件重建 `DecisionInputBinding`，`current_validity = current_input_validity(binding, current.facts)`；`canonical/decision_inputs.py:66-97`：`all_facts` 范围的 `_read` 返回排除后的**整个字典**，逐引用做值 hash 比对，任一不等 → `stale`。
6. **重放身份**：`canonical/study_definition.py:424-454` 与 `:751-786` — `decision_input_refs` 参与 `_fact_updates_sha256`，即同 CAS 重放要求引用材料逐字节一致；但**回执找回**（`lookup_decision`，`service.py:629-658`）只比对 `DecisionRecord.material_sha256()` 与事件中的 idempotency_key/cas_identity，**与引用无关**；`application/adoption.py:554-570` 的意图 hash 重算只读取**事件内存储的**引用。
7. **队列消费**：`agent5/coordinator.py:482-501` 决策请求队列收录 `stale` 记录；前端 `RegimenAdoptionCard.jsx:55-58,135-141` 将 `stale` 呈现为“需重新核对”。
8. **现行测试钉死的行为**：`tests/protocol_v3/integration/test_regimen_adoption_api.py:95-106` — 源资料变化与临床事实变化（`picos.phase`）都必须使 `decision:dose-regimen` → `stale`；`test_decision_input_binding.py:32-39` — `all_facts` 检测新增键且记账键噪声豁免。
9. **词汇封闭性**：`tp_ma_07_v2/fact_bindings.json` 含 743 条绑定、**728 个不同 canonical 路径**（≈28KB JSON），经 `registries/fact_bindings.py` 的 `FactBindingCatalog` 校验并由 `registries/template_runtime.py:30-36` `load_current_template` 装配。
10. **计划对该问题的原话**（`plans/mw_protocol_v3_implementation_plan_v3_20260912.md` “完整初稿调度前的当前接线义务”）：剩余 7 类高风险卡接线前须处理现有 all_facts 读集；不能简单删除读集掩盖真实依赖；区分“生成输入是否变化”与“医学确认是否受影响”；不把单张给药卡通过当八卡通过。

### 3. 缺陷与反例（观察 + 推断分列）

**主缺陷（已复现）**：确认有效性被生成读集整体劫持。反例序列：采用剂量（facts_v1）→ 终点卡采用 `endpoints.primary_efficacy` → 样本量卡采用 `statistics.sample_size.reproducible_result` → 剂量卡 `stale`（A2）。

**次生放大（推断，基于 source 证据链）**：假 `stale` 的剂量卡无法用“原 run 再确认”清除——`design.py:266-271` 的新鲜采用门会因临床事实已变而 409；同 intent 重放虽返回原回执但绑定未更新，卡片永远回不到 `current`。清除一次假 stale 的真实代价 = 重新 prepare（读入当前事实）+ 重新生成（一次真实模型调用）+ 重新确认。按 8 卡顺序采用，最坏需 Σ(k−1)=28 次此类清除 → 远超 ≤20 点击预算，且每次都是模型调用。这直接违反原生 Goal 的 20/5 预算与“无关修改不重开”。

**杀死若干廉价替代的具体反例**：
- **纯 scoped 引用列表（无 catch-all）**：范围表漏列医学相关新路径（如 `population.*` 下与剂量耦合的键，`v2_n_4_3` 合同明确要求 `picos.intervention_dose_regimen.population_link`）→ 剂量保持 `current` 而医学依据已变 = 假阴性，科学正确性事故（B7 证明 catch-all 可堵住）。
- **按前缀推断相关性**：`intervention.*` 前缀会漏 `picos.intervention_dose_regimen.*` 别名族与 `framing.study_phase`；而“与剂量同章共消费”推导会经 synopsis（`v2_n_1_1` 同时要求 `synopsis.interventions` 与 `synopsis.sample_size`）把样本量又拉回相关 → 退回全重开。章节级 3R.4C 图不能直接当决策级范围用。
- **批量一次确认八卡**：首过省点击，但任一成员的相关变化重开整批，迭代时被迫重确认七个未变决定，逐卡审计语义也被稀释；与计划“逐卡确认到整稿”的已宣告方向冲突。

### 4. 推荐的最小连贯集成（建议，标注为推荐而非事实）

**核心区分**：`decision_input_binding` 继续 = “生产者实际读了什么”（事实/披露证明 + 重放 CAS 材料）；新增 `confirmation_binding` = “此确认的医学依赖是什么”（服务端声明的策略，采用时物化并冻结进事件）。

**改动面（5 处，全部增量）**：
1. **新配置** `config/.../tp_ma_07_v2/decision_confirmation_scopes.json`：逐 `decision_key` 给出 `relevant`/`irrelevant` 对 728 个 canonical 路径的完全分类 + `source_refs`（医学审阅出处）+ `unknown_policy: "reopen"`；仿 `FactBindingCatalog` 做完备性校验（每键覆盖全目录、两集合不相交），在 `template_runtime.load_current_template` 装配并 hash 绑定模板。允许 JSON 内用确定性域规则展开成路径清单以降低手工量——展开发生在采用物化时，事件仍存展开后的完整清单，读路径不自依赖配置（保证历史稳定：模板后续修订不会回溯翻转旧有效性）。
2. **`application/commands.py`**：`ApplyStudyDecisionCommand` 增加可选 `confirmation_input_refs`（`__post_init__` 用现有 `input_refs_payload` 校验）。
3. **`agent2/study_definition.py`**：`prepare_regimen_adoption` 从范围表物化确认引用 = 相关路径逐条 `fact` 引用（可含 `members`）+ 一条 catch-all `all_facts(excluded = 记账键 ∪ irrelevant 分类集)`，作为 `confirmation_input_refs` 传入；原 `decision_input_refs` 不动。
4. **`application/service.py`**：:572-575 处并列写入 `payload["confirmation_binding"]`（存在时）；`get_decision_graph`（:885-908）优先取 `confirmation_binding`，缺失则回落 `decision_input_binding`。
5. **测试**：新增范围语义单测（B1–B9 场景）+ 集成用例“采用剂量→采用终点→剂量仍 current；改期别→剂量 stale；未知新键→stale”。现有两支允许单测与冻结集成测试行为不变（`research.input_context` 仍在相关集 → 'source' 参数化仍 stale；`picos.phase` 是未分类 fixture 键 → catch-all 翻 stale，'clinical' 参数化仍 stale）。

**旧记录行为（迁移语义）**：旧事件无 `confirmation_binding` → 读路径回落 → 与今天逐字节同行为（含 all_facts 假阳性），不删除、不重算、不回溯改写任何历史绑定；旧 intent 经 `lookup_decision` 找回与引用无关，不受影响；同 key 新引用的 fresh 重放按 CAS 纪律正确 409。旧研究要享受范围语义需一次再确认（该次再确认本就要求按当前事实重新生成）。全新研究的 8 卡路径从第一卡起即带范围语义。

**为何不采用更小的单绑定改法**（把 irrelevant 集并进现有 all_facts 的 exclusions、不加第二绑定）：它是最小 diff（2 文件），但把“读集事实”与“确认策略”在事件模式里永久混同——事件里的 `decision_input_binding` 从此对 2026-09-13 之后的新事件不再是完整披露证明，`recompute_adoption_intent_sha256` 等下游与审计假设被静默改义。二绑定多约 20 行、3 个服务文件，换来两个不变量各自成名、新旧事件同构。这正是合同要求的“区分生成输入是否变化与医学确认是否受影响”的结构化落点。

**成本与已知代价**：catch-all 需物化完整 irrelevant 清单（~726 路径 ≈27KB/卡/事件，8 卡全程 ≈216KB 事件载荷）——sqlite 与现事件规模（template_adoption 已携带 impact plan）可承受；若后续过大，可升级为命名范围引用（`DecisionInputRef` 增 `declared_scope` 字 + 声明 hash），但那要动冻结 canonical 模型与其 4 支钉死测试，本轮不值得。成员级精度（`members`）已可用于复合事实。

### 5. 八卡路径的点击核算（推断）

新路径下：8 次采用确认（8 点击）+ 后续无关卡采用零重开（B1–B4）→ 预算内完成全部八卡；相关变化（如剂量改值导致终点卡范围命中）只重开真实受影响卡，且重开链有限收敛（再确认不改事实值即不再触发任何重开，结构性无环）。对照现行最坏 28 次强制“再生成+再确认”。

### 6. 最高影响缺陷/不确定性、异议与给 Codex 的有界问题

**异议（对初始表述的修正）**：合同句“不假装以文件名前缀知无关/相关”同样适用于**章节共消费推导**——我核对 `v2_n_1_1`/`v2_n_4_3`/`v2_n_6_1_2` 合同后确认，任何从章节图机械推导决策范围的路线都会经 synopsis 全科共消费退化为全重开。范围表必须是独立的医学声明工件，不能由任何现有图自动“推导”后免审。

**未决科学决策（需 Codex/医学 owner，非本审阅权限）**：八卡的 `decision_key` 清单与每卡 relevant 集内容。机制完全内容无关；我不在本报告内发明任何临床分类。`research.input_context` 建议对所有卡保持相关（现行集成测试对剂量钉死了该语义，源资料变化应使确认过期——与计划 82 行义务一致）。

**有界问题 1（阻塞范围表验收，不阻塞机制设计）**：八类高风险卡的精确 decision_key 与 relevant 分类由谁作者化、以何医学审阅记录作 `source_refs`？安全临时路径：先只给 `decision:dose-regimen` 建表（relevant = `intervention.dose_regimen`、`intervention.product_identity`、`picos.intervention_dose_regimen.comparator_regimen`、`framing.study_phase`、population 耦合键、`research.*` 两键；irrelevant = 其余全部），其余键未建表时生产者不传 `confirmation_input_refs` → 行为同今天，逐卡迁移。

**有界问题 2（机制选择确认）**：是否接受“两绑定 + 事件内物化排除清单”作为本轮集成（我推荐），还是接受更小的单绑定改法并显式接受其披露语义弱化？两者我都已在 §4 给出后果。

**剩余不确定性（诚实申报）**：(a) 我未运行集成/API 级测试（边界只允许两支单测），§4 第 5 点的测试效果是设计推断；(b) 事件载荷增长未做 sqlite 容量实测；(c) 范围表完备性校验只能证明机械全覆盖，不能证明医学正确性——后者只能由 source_refs 指向的医学审阅承担；(d) 前端 `RegimenAdoptionCard.jsx:55` 硬编码单一 decision_key，八卡化时的 UI 复用是 V1.4 既定工作，不属本架构变更。

**证据/推断/建议/不确定性分界**：§1–§3 为源码与复现证据（可独立复核）；§4–§5 为基于证据的设计建议与推断核算；§6 为显式未决项。本输出不构成临床、监管、Word 或产品验收；最终采纳与实施由 Codex 裁定。
