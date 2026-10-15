# 自检阻断修复 · 纪元R2第3次自检红节点⑤（2026-10-15，实现师，本ask内实跑）

## 红节点（承接自检报告）
⑤初稿分章生成：写作入口锁死（第3型死锁）——product_profile四字段
（技术类型/暴露范围/给药途径/剂型）建项填写后仅剂型落库、语料门不含画像、
assembly 以 authoritative_fact_required 拦投影（英文提示直出）、完成后态
表单补填被重置循环。

## 根因定位（读码+读库实证，比任务书判定更精确的统一机制）
- **r2-2 事件表**：rev10 framing_committed 的 changed_fields 仅
  design_pattern/intrinsic_objectives/population_intent——画像字段从未进入
  任何提交；当前库画像全默认（technology_type=unknown/routes=[]/
  exposure=unknown/dosage_forms=[]）。
- **统一根因＝mergeIncomingPreservingLocal 对哨兵值的覆盖**（Setup.jsx）：
  脏态合并的标量分支"incoming非空即整替"，而服务端快照的画像标量是
  哨兵值'unknown'（非空字符串）→ 任何旅程写回（自动检索的草稿保存回包/
  刷新应用）把用户刚填的'小分子'/'全身暴露'清回'unknown'。数组分支本就
  "本地非空保留"→ 给药途径/剂型存活——**这正是"四字段只有数组类存活
  （任务书早期观察到dosage_forms在库）、两个标量被清"的1/4签名**。
  建项丢失与完成后态重置循环（'小分子'->'unknown'三种React设值法实测）
  是同一机制的两个时点表现。
- **英文提示直出**：装配阻断项标签查 ASSEMBLY_PLAN_BLOCKER_LABELS，表内
  无 product.*/画像 fact_path 条目 → 回落 question.prompt（英文原文），
  违反20261003b人话化。
- **跳转错组（观察D）**：'查看待确认项'硬编码 setStage("picos")/
  setGroup("intervention")，画像阻断时用户被送去干预组而非项目与产品。

## 修复（反例先红后绿；修链路功能非绕测试，全部前端 Setup.jsx）
1. **merge哨兵判定**：'unknown'/'undecided' 视为合并语义空值——服务端
   快照带哨兵回写永不覆盖本地真实值（isMergePlaceholderValue）。
   一处修复同时闭死锁臂(1)建项丢失与(4)完成后态重置：完成后态补画像
   →值存活→完成第一步（影响确认面板）→落库→assembly阻断消除。
2. **阻断项人话化**：ASSEMBLY_PLAN_BLOCKER_LABELS 增补画像四字段+
   product.*/evidence.systemic_oral_defaults/ip_adjustment_policy 条目；
   authoritative_fact_required 无映射时用中文模板（"需确认权威设计事实：
   <字段中文名>"）——英文prompt不再直出。
3. **跳转按事实路径选组**：查看待确认项按首个阻断项fact_path导航
   （framing.product_profile*→第一步/项目与产品；picos.intervention*→
   干预组；其余→执行与统计），不再误跳。

## 反例与测试（先红后绿实证，git stash摘除组件改动证红）
- 单元（新文件 mergeIncomingPreservingLocal.sentinel.test.mjs）：服务端
  unknown/空数组回写时本地四字段全保留——修前2红（标量被清/undecided
  被清）修后3绿（含"本地为空时服务端真实值照常合入"的反向守护）。
- 端到端场景（escape测试文件新增）：第一步填画像四字段→保存草稿（服务端
  回包带unknown画像=现场clobber向量）→表单值存活→完成第一步→commit体
  含全部四值——修前红（表单被清、commit丢字段）修后绿。
- 人话化（assemblyPlanConfirmEntry新增）：画像权威事实阻断显示
  "还需确认：药物技术类型、给药途径…"且不含英文原文——修前红修后绿
  （既有的给药方案中文指引测试保持绿）。

## FAST定向自查（本ask内实跑）
- 全库存：41文件/233测试全绿（新增4件）；后端未改（前端-only修复），
  vite dev从盘HMR即时生效（5186→200）；桥接套件抽测103绿。
- **真机阻断面实证**：GET r2-2 protocol-assembly-plan——
  deterministic_projection_allowed=False，blocker=画像四fact_path
  （product.modality/route/dosage_form/exposure_scope + evidence.
  systemic_oral_defaults），prompt英文原文与任务书一致——修复后这些
  blocker将显示中文字段名；画像一旦经（不再被清的）表单落库，blocker
  即消除（blocker就是这些fact_path的未确认态）。
- 辅助观察（如实）：以手拼framing体直接POST impact-preview被422
  （表单走规范化payload；手拼体含派生字段未逐一排查）——未追，不影响
  本修复结论（端到端行为由挂载级测试按真实组件路径覆盖）。

## 下一轮自检预期⑤路径
完成后态进'项目与产品'补画像四字段（值存活）→完成第一步（影响确认）→
画像落库→assembly阻断清零（中文提示）→进入写作平台→⑤-⑧解锁。
若仍有ip_adjustment_policy警告项，其为warning级非阻断。

## 账本转交（任务书观察，未修）
- C：PICOS表单13项手填交互复杂（label与missing提示不一致/误填污染）；
- E：分诊终确认需点两次；
- B（上轮）：一键确认合格候选按钮循环。
（A=本修复主体；D=跳转已修）

## 红线自检
未碰 live 8910/医学监查；模型服务器零接触（本ask无AI调用）；未清库未
reset（零业务行写入——impact-preview为只读端点）；未动immutable；
反例先红后绿（stash三组证红）；主会话并行未提交改动零触碰。
