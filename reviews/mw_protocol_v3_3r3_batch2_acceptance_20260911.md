# 3R.3 batch2 验收（主owner裁定）— 2026-09-11

- 验收对象：16个背景/目的/estimand载体（v2_n_2_*、v2_n_3_*）：合同+技能+batch2.json
  （77 fixtures）+ test_chapter_batch2.py（38测试）。
- 执行血统：codebuddy/deepseek-v4.1-flash:max（恢复派发，交付原batch2范围），
  报告 runs/mw_protocol_v3_3r3_batch2_resume_20260911/report_codebuddy_batch2_resume.md。
- 主owner验证：组合套件97/68/38复计一致、注册表组装语义复现、partial lint exit0
  （covered 16/111，486条延迟义务申报）。越界审计清白（core/assembler/batch1未动）。
- Fresh独立复核：zcode/GLM-5.3-Flash（非deepseek家族验证者），
  报告 runs/mw_protocol_v3_3r3_batch2_fresh_20260911/report_zcode_batch2_fresh.md，
  **VERDICT: ACCEPT，DEFECTS: None**。B1-B8全PASS：16身份/模板哈希/书签样式精确匹配；
  estimand第五属性仅v2_n_3_1_2_4且不作为ICE；picos.population_summary无词汇冲突；
  竞品vs本品证据组分离且IB文件号不构成匹配上下文；无标题PK/毒理/一般药理四独立义务
  不可由一段满足；27证据组每组单一准入claim+上下文窗口+质量门槛，零mega-group；
  13条定向负例各因目标原因失败；合成标记完整；RED先于实现（XML时间戳链一致）。
  复核者独立执行38/38通过。

## 裁定：ACCEPTED（2026-09-11，ZCode主owner）

文件边界已随 commit b0b3663 入库。

## 接受范围与仍有效的限制

- 接受：16载体的合同/技能/fixture结构、源义务绑定、批次范围断言。
- 仍然deferred（复核者残余风险与worker申报一致）：真实DOCX再读（node_tree前提）、
  条件规则运行时执行、方法名-only值的医学判别、真实来源准入、Word渲染——
  属3R后续任务与6R/7R义务。
- partial lint 永远 incomplete；本验收不代表全注册表（111）或产品验收。
