# 3R.3 batch5 验收（主owner裁定）— 2026-09-11

- 验收对象：19个评估/安全性载体（v2_n_9_1..4、v2_n_10_1_1..6、v2_n_10_2_1..3、
  v2_n_10_3_1..3、v2_n_10_4/5/6）：合同+技能+batch5.json（113 fixtures）+
  test_chapter_batch5.py（41测试）。
- 执行血统：codebuddy/deepseek-v4.1-flash:max，报告
  runs/mw_protocol_v3_3r3_batch5_20260911/report_codebuddy_batch5.md。
- 主owner验证：组合套件158→179（batch1-7）、独立组装19章/113 fixtures、越界审计清白。
- Fresh独立复核：zcode/GLM-5.3-Flash（非deepseek家族），报告
  runs/mw_protocol_v3_3r3_batch5_fresh_20260911/report_zcode_batch5_fresh.md，
  VERDICT: ACCEPT_WITH_ACTIONS。E2-E8全PASS（AE/SAE/TEAE分类学、双报告时钟、五级因果
  术语逐字、妊娠8事实+3禁令、CTCAE项目绑定、IRC/安全委员会分立、证据组singleton、
  34/34负例定向失败0错配——复核者独立复现41/41并逐条审计负例）；
  E1 FAIL仅word_rules（D1同型复发）。

## 裁定：ACCEPTED（2026-09-11 22:43，ZCode主owner，五缺陷修复后）

| # | 缺陷 | 修复 |
|---|---|---|
| D1 | 19合同required_styles空（batch4 D1同型复发，checker不交叉校验） | node_tree程序化回填（19处） |
| D2 | 16合同书签仅存主_Toc、丢node_tree其余书签（如_Hlk） | 完整书签列表回填（16处） |
| D3 | v2_n_9_1/9_2虚构交叉引用soa_table_1（仅测试fixture存在） | 置[]（SoA一致性已由事实+QC规则承载） |
| D4 | 10_2_3 ctq问题混入日文"と" | 改"与" |
| D5 | 10_1_4技能provenance窗口651-661越界（651属无主段） | 改652-661 |

组合套件179/179（post_repair_combined_1to7.xml）。

复核者残余风险与改进项：word_rules三类字段无checker交叉校验（样式/书签/交叉引用），
仅复核可拦截——已列为3R改进项（与batch4复核同记，将纳入3R.5或core lint增强）；
DOCX未开依node_tree（全批统一延后源核对）。

## 接受范围与仍有效的限制

- 接受：19载体合同/技能/fixture结构、AE/SAE/TEAE/严重性/预期性/因果全分类学分型、
  研究者SAE与申办方SUSAR双时钟、妊娠语义、CTCAE/AESI项目绑定、父体继承、
  34负例定向失败。
- 仍然deferred：条件规则运行时执行、医学判断、真实来源准入（IB/PV/SOP）、
  Word渲染。partial lint永远incomplete。
