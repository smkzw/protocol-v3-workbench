# 3R.3 batch3 验收（主owner裁定）— 2026-09-11

- 验收对象：10个设计/人群载体（v2_n_4_1..5、v2_n_5_1..5）：合同+技能+batch3.json
  （48 fixtures）+ test_chapter_batch3.py（20测试）。
- 执行血统：omp/pi openai-codex/gpt-5.6-luna:xhigh，报告
  runs/mw_protocol_v3_3r3_batch3_20260911/report_omp_batch3.md。
- Fresh独立复核（两段血统）：grok/grok-4.6两次harness侧截断（exit0但stopReason=
  cancelled，已记fallback lineage，grok路线弃用于本任务）；改派
  codebuddy/deepseek-v4-flash（非OpenAI家族验证者），报告
  runs/mw_protocol_v3_3r3_batch3_fresh_20260911/report_codebuddy_batch3_fresh.md，
  VERDICT: ACCEPT_WITH_ACTIONS。D1-D8裁决：6 PASS + D2 PARTIAL（见缺陷）。
  复核者在plan模式无法执行Bash，依静态核验+主owner提供的XML证据；主owner独立运行
  测试（117/158通过）补足该残余风险。

## 裁定：ACCEPTED（2026-09-11 22:25，ZCode主owner，三缺陷修复后）

| # | 缺陷 | 修复 | 证据 |
|---|---|---|---|
| D1 | 过时编号交叉引用义务错绑v2_n_4_2（源段355无依据）；spec定位源段364=v2_n_4_5首个内容段；4_5缺canonical-target义务与366 GCP条号出处保留 | 4_2删除355句；4_5新增两project_specific_elements（364解析义务+366出处保留不替代核验）；负例fixture重绑至4_5（克隆4_5 positive，仅allocation组证据locator改figure+过时编号，附negative_reason verdict）；测试映射同步；vocab登记条件路径 | v2_n_4_2/4_5.json、batch3.json、test_chapter_batch3.py |
| D2 | 避孕保留义务未达排除载体（reconciliation要求纳入/排除双载体） | 5_2新增合同级conditional_applicability_rules（schema正确位置）：picos.risk.pregnancy_contraception触发→排除标准引用纳入载体事实，不复制逆命题不设通用期限；project_specific_element同步说明 | v2_n_5_2.json |
| D3 | 新事实根（population.lifestyle/recruitment/retention/rescreening、picos.risk.pregnancy_contraception）缺归属声明 | 5_1/5_3/5_4/5_5各补一句归属声明（共享命名空间/StudyDefinition承载/无章内第二存储） | 各合同project_specific_elements |

修复过程暴露并修正一处实现失误：条件规则首插于substantive_content（schema
extra_forbidden，20测试立即失败）——移至合同顶层正确字段后恢复。组合套件
158/158（post_repair_combined_1to5_v2.xml）。

复核者残余风险裁定：355/364/366段落定位依spec+node_tree推断（DOCX未开）——与
batch2/4先例一致，记入3R后续统一源核对；"接受人工医学与质量复核"样板句可满足
high-risk决策测试的风险——记为3R.4/3R.5依赖图与QC registry输入。

## 接受范围与仍有效的限制

- 接受：10载体合同/技能/fixture结构、父体继承、谓词分型、高危决策非默认、
  8负例定向失败（含重绑后的stale-reference）。
- 仍然deferred：条件规则运行时执行、医学判断、真实来源准入、Word渲染；
  partial lint永远incomplete。文件已在commit 7118329入库（修复增量将随下个
  commit边界提交）。
